import logging
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from saude.models import ConsultaMedica, PerfilSaude, Titular

logger = logging.getLogger("saude.gcal")

PALAVRAS_CHAVE_SAUDE = [
    "consulta", "trofa saúde", "cuf", "hospital", "dentista", "psiquiatr",
    "psicolog", "pediat", "médic", "oftalmolog", "imunoalergolog", "fisioterapi",
    "cardiolog", "dermatolog", "injeccao", "exame", "análises", "otorrino", "desenvolvimento"
]


def _parse_dt(val_str: str) -> Optional[datetime]:
    """Converte strings iCal como 20260831T140000Z ou 20260831 em datetime UTC."""
    val_clean = val_str.strip()
    if ":" in val_clean:
        val_clean = val_clean.split(":")[-1].strip()

    if len(val_clean) == 8 and val_clean.isdigit():
        return datetime(int(val_clean[:4]), int(val_clean[4:6]), int(val_clean[6:8]), 9, 0, tzinfo=timezone.utc)

    if "T" in val_clean:
        partes = val_clean.split("T")
        d_part = partes[0]
        t_part = partes[1].replace("Z", "")
        if len(d_part) == 8 and len(t_part) >= 4:
            try:
                y = int(d_part[:4])
                m = int(d_part[4:6])
                d = int(d_part[6:8])
                h = int(t_part[:2])
                mn = int(t_part[2:4])
                return datetime(y, m, d, h, mn, tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def parse_vevents_pure(content: str) -> List[Dict[str, Any]]:
    """Parse de VEVENTs usando apenas regex e stdlib."""
    eventos = []
    content_unfolded = re.sub(r"\r?\n[ \t]", "", content)
    raw_events = content_unfolded.split("BEGIN:VEVENT")
    for block in raw_events[1:]:
        if "END:VEVENT" not in block:
            continue
        body = block.split("END:VEVENT")[0]
        props = {}
        for line in body.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            k, v = line.split(":", 1)
            k_base = k.split(";")[0].upper()
            if k_base not in props:
                props[k_base] = v

        summary = props.get("SUMMARY", "").replace(r"\,", ",").replace(r"\;", ";").strip()
        location = props.get("LOCATION", "").replace(r"\,", ",").replace(r"\;", ";").strip()
        dtstart_str = props.get("DTSTART", "")
        dt_val = _parse_dt(dtstart_str)
        if dt_val and summary:
            eventos.append({
                "summary": summary,
                "location": location,
                "dt": dt_val,
            })
    return eventos


def normalizar_especialidade(titulo: str) -> str:
    """Extrai uma especialidade médica limpa do título do evento."""
    t = titulo.strip()
    
    # Padrão: "Trofa Saúde - Consulta <Especialidade>"
    m = re.search(r"consulta\s+(?:de\s+)?([^-\(\n]+)", t, re.IGNORECASE)
    if m:
        esp = m.group(1).strip()
        # Limpar nomes de hospital no fim
        esp = re.sub(r"\b(hospital|instituto|cuf|porto|trofa|saúde|alfena|boa nova)\b.*", "", esp, flags=re.IGNORECASE).strip()
        if esp:
            return esp.title()

    if "dentista" in t.lower():
        return "Medicina Dentária"
    if "injeccao" in t.lower():
        return "Tratamento / Enfermagem"
    if "fisioterapia" in t.lower() or "fisio" in t.lower():
        return "Fisioterapia"
    if "oftalmologia" in t.lower():
        return "Oftalmologia"
    if "psiquiatria" in t.lower():
        return "Psiquiatria"
    if "psicologia" in t.lower():
        return "Psicologia"
    if "cardiologia" in t.lower():
        return "Cardiologia"

    return "Consulta Médica"


def extrair_local_clinica(summary: str, location: Optional[str]) -> str:
    """Determina o hospital ou clínica a partir do local ou do título."""
    loc = (location or "").strip()
    sum_low = summary.lower()

    if "trofa saúde" in sum_low:
        subloc = loc if loc else ("Alfena" if "alfena" in sum_low else ("Boa Nova" if "boa nova" in sum_low else ""))
        return f"Hospital Trofa Saúde {subloc}".strip()
    if "cuf" in sum_low:
        return f"Hospital CUF {loc}".strip() if loc else "Hospital CUF Porto"
    if "santo antónio" in sum_low or "sto antonio" in sum_low or "hgsa" in sum_low:
        return "Centro Hospitalar Universitário de Santo António"
    if "são joão" in sum_low or "hsj" in sum_low:
        return "Centro Hospitalar Universitário de São João"

    return loc or "Consultório / Clínica"


async def sincronizar_google_calendar_saude(session: AsyncSession, ical_url: str) -> int:
    """
    Descarrega o iCal do Google Calendar, extrai consultas médicas e sincroniza
    com a base de dados de Saúde Familiar para cada perfil familiar.
    """
    if not ical_url:
        return 0

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(ical_url)
            if resp.status_code != 200:
                logger.warning(f"Erro ao obter iCal do Google Calendar: {resp.status_code}")
                return 0
            ical_text = resp.text
    except Exception as e:
        logger.error(f"Exceção ao ligar ao Google Calendar iCal: {e}")
        return 0

    eventos_cal = parse_vevents_pure(ical_text)
    if not eventos_cal:
        return 0

    # Carregar perfis existentes com titulares carregados
    from saude.repositories import saude_repo
    perfis = await saude_repo.listar_perfis(session)
    if not perfis:
        return 0

    perfil_alex = next((p for p in perfis if p.titular and "alex" in p.titular.nome.lower()), perfis[0])
    perfil_sam = next((p for p in perfis if p.titular and "sam" in p.titular.nome.lower()), None)
    perfil_charlie = next((p for p in perfis if p.titular and "charlie" in p.titular.nome.lower()), None)

    # Carregar consultas existentes para evitar duplicados
    stmt_cons = select(ConsultaMedica.perfil_id, ConsultaMedica.data_hora)
    res_cons = await session.execute(stmt_cons)
    existentes = set((r[0], r[1].replace(tzinfo=timezone.utc) if r[1].tzinfo is None else r[1]) for r in res_cons.all())

    agora = datetime.now(timezone.utc)
    novos_inseridos = 0

    for ev in eventos_cal:
        summary = ev["summary"]
        dt_hora = ev["dt"]
        location = ev["location"]

        # Filtrar apenas eventos médicos
        sum_low = summary.lower()
        if not any(k in sum_low for k in PALAVRAS_CHAVE_SAUDE):
            continue

        # Ignorar compromissos muito antigos (anteriores a 2024)
        if dt_hora < datetime(2024, 1, 1, tzinfo=timezone.utc):
            continue

        # Determinar perfil do paciente
        if perfil_charlie and any(k in sum_low for k in ["charlie", "infância", "pedopsiquiatria", "pediátric", "pediatra"]):
            perfil_alvo = perfil_charlie
        elif perfil_sam and "sam" in sum_low:
            perfil_alvo = perfil_sam
        else:
            perfil_alvo = perfil_alex

        # Verificar se já existe (tolerância de 30 min)
        ja_existe = any(
            p_id == perfil_alvo.id and abs((d_hora - dt_hora).total_seconds()) < 1800
            for p_id, d_hora in existentes
        )
        if ja_existe:
            continue

        especialidade = normalizar_especialidade(summary)
        local_clinica = extrair_local_clinica(summary, location)
        
        # Concluída se já passou
        concluida = dt_hora < agora

        nova_consulta = ConsultaMedica(
            perfil_id=perfil_alvo.id,
            data_hora=dt_hora,
            especialidade=especialidade,
            medico=None,
            local_clinica=local_clinica,
            motivo=summary,
            preparacao_instrucoes=None,
            diagnostico_notas=None,
            custo=Decimal("0.00"),
            concluida=concluida,
            codigo_confirmacao=None,
            documento_id=None,
        )
        session.add(nova_consulta)
        existentes.add((perfil_alvo.id, dt_hora))
        novos_inseridos += 1

    if novos_inseridos > 0:
        await session.commit()
        logger.info(f"Sincronizadas {novos_inseridos} consultas médicas do Google Calendar!")

    return novos_inseridos
