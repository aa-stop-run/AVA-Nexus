import calendar
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

NOMES_MESES = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
]


async def _garantir_tabela_ignorados(session: AsyncSession):
    """Garante que a tabela de eventos ocultados/ignorados existe."""
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS evento_calendario_ignorado (
                id VARCHAR(255) PRIMARY KEY,
                criado_em TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """))
        await session.commit()
    except Exception as e:
        print(f"Erro ao garantir tabela de eventos ignorados: {e}")


async def obter_ids_ignorados(session: AsyncSession) -> set[str]:
    """Retorna conjunto de IDs de eventos que foram eliminados da app."""
    try:
        await _garantir_tabela_ignorados(session)
        res = await session.execute(text("SELECT id FROM evento_calendario_ignorado"))
        return {row[0] for row in res.fetchall()}
    except Exception as e:
        print(f"Erro ao consultar eventos ignorados: {e}")
        return set()


async def obter_agenda_unificada(
    session: AsyncSession,
    ano: Optional[int] = None,
    mes: Optional[int] = None
) -> Dict[str, Any]:
    """Agrega eventos de Saúde, Veículos, Finanças e Calendário Pessoal num feed unificado."""
    hoje = date.today()
    alvo_ano = ano or hoje.year
    alvo_mes = mes or hoje.month

    # Limites do mês
    _, ult_dia = calendar.monthrange(alvo_ano, alvo_mes)
    inicio_mes = date(alvo_ano, alvo_mes, 1)
    fim_mes = date(alvo_ano, alvo_mes, ult_dia)

    eventos: List[Dict[str, Any]] = []

    # 1. Consultas de Saúde
    try:
        res = await session.execute(text("""
            SELECT c.id, c.data_hora, c.especialidade, c.medico, c.local_clinica, t.nome as paciente
            FROM consulta_medica c
            JOIN perfil_saude p ON p.id = c.perfil_id
            JOIN titular t ON t.id = p.titular_id
            WHERE c.data_hora::date BETWEEN :inicio AND :fim
            ORDER BY c.data_hora ASC;
        """), {"inicio": inicio_mes, "fim": fim_mes})
        for r in res.mappings():
            dt = r["data_hora"]
            eventos.append({
                "id": f"saude-{r['id']}",
                "origem_id": str(r["id"]),
                "titulo": f"Consulta: {r['especialidade']}",
                "subtitulo": f"{r['paciente']} • {r['local_clinica'] or ''} {('- ' + r['medico']) if r['medico'] else ''}".strip(),
                "data": dt.strftime("%Y-%m-%d"),
                "hora": dt.strftime("%H:%M") if hasattr(dt, "strftime") else "00:00",
                "tipo": "saude",
                "cor": "rose",
                "icone": "stethoscope",
                "local": r["local_clinica"] or "",
                "origem": "saude",
                "editavel": True,
            })
    except Exception as e:
        print(f"Erro ao recolher consultas para agenda: {e}")

    # 2. Veículos: Próxima IPO e Maintenance
    try:
        res = await session.execute(text("""
            SELECT id, nome, matricula, data_proxima_ipo
            FROM veiculo
            WHERE ativo = true AND data_proxima_ipo BETWEEN :inicio AND :fim
            ORDER BY data_proxima_ipo ASC;
        """), {"inicio": inicio_mes, "fim": fim_mes})
        for r in res.mappings():
            dt = r["data_proxima_ipo"]
            eventos.append({
                "id": f"veiculo-ipo-{r['id']}",
                "origem_id": str(r["id"]),
                "titulo": f"Inspeção IPO: {r['nome']}",
                "subtitulo": f"Plate {r['matricula'] or '—'}",
                "data": dt.strftime("%Y-%m-%d"),
                "hora": "09:00",
                "tipo": "veiculo",
                "cor": "emerald",
                "icone": "car",
                "local": "Centro de Inspeções",
                "origem": "veiculos",
                "editavel": False,
            })
    except Exception as e:
        print(f"Erro ao recolher veículos para agenda: {e}")

    # 3. Finanças: Débitos e Recurring Subscriptions
    try:
        res = await session.execute(text("""
            SELECT r.id, r.descricao, r.valor, r.dia_do_mes, c.nome as categoria
            FROM recorrente r
            LEFT JOIN categoria c ON c.id = r.categoria_id
            WHERE r.ativo = true AND r.dia_do_mes BETWEEN 1 AND :ult_dia
            ORDER BY r.dia_do_mes ASC;
        """), {"ult_dia": ult_dia})
        for r in res.mappings():
            dia = min(r["dia_do_mes"], ult_dia)
            data_ev = date(alvo_ano, alvo_mes, dia)
            eventos.append({
                "id": f"financas-rec-{r['id']}",
                "origem_id": str(r["id"]),
                "titulo": f"Débito: {r['descricao']}",
                "subtitulo": f"€ {float(r['valor']):,.2f} • {r['categoria'] or 'Despesa'}",
                "data": data_ev.strftime("%Y-%m-%d"),
                "hora": "08:00",
                "tipo": "financas",
                "cor": "cyan",
                "icone": "receipt",
                "local": "Primary Bank / Direct Debit",
                "origem": "financas",
                "editavel": False,
            })
    except Exception as e:
        print(f"Erro ao recolher finanças recorrentes para agenda: {e}")

    # 4. Eventos Pessoais e Familiares (tabela evento_calendario)
    try:
        res = await session.execute(text("""
            SELECT id, titulo, descricao, data_inicio, data_fim, tipo, local
            FROM evento_calendario
            WHERE data_inicio::date BETWEEN :inicio AND :fim
            ORDER BY data_inicio ASC;
        """), {"inicio": inicio_mes, "fim": fim_mes})
        for r in res.mappings():
            dt = r["data_inicio"]
            eventos.append({
                "id": str(r["id"]),
                "origem_id": str(r["id"]),
                "titulo": r["titulo"],
                "subtitulo": r["local"] or r["descricao"] or "",
                "data": dt.strftime("%Y-%m-%d"),
                "hora": dt.strftime("%H:%M") if hasattr(dt, "strftime") else "00:00",
                "tipo": r["tipo"] or "pessoal",
                "cor": "violet",
                "icone": "calendar",
                "local": r["local"] or "",
                "origem": "pessoal",
                "editavel": True,
            })
    except Exception as e:
        print(f"Erro ao recolher eventos pessoais para agenda: {e}")

    # 4. Google Calendar (iCal Privado)
    try:
        from hub.config import get_settings
        from hub.services.google_calendar_service import obter_eventos_google_calendar
        settings = get_settings()
        if settings.google_calendar_ical_url:
            g_events = await obter_eventos_google_calendar(settings.google_calendar_ical_url)
            ignorados = await obter_ids_ignorados(session)
            m_str = f"{alvo_mes:02d}"
            a_str = str(alvo_ano)
            for ge in g_events:
                if ge["id"] in ignorados or ge.get("origem_id") in ignorados:
                    continue
                if ge["data"].startswith(f"{a_str}-{m_str}"):
                    # Deduplicação inteligente com saúde
                    ja_existe_consulta = any(
                        e.get("tipo") == "saude" and e.get("data") == ge["data"]
                        for e in eventos
                    )
                    if not ja_existe_consulta:
                        eventos.append(ge)
    except Exception as e:
        print(f"Erro ao recolher Google Calendar para agenda unificada: {e}")

    # Ordenação cronológica
    eventos.sort(key=lambda x: (x["data"], x["hora"]))

    # Mapeamento de dias com eventos para pontos luminosos (dots)
    dias_com_eventos: Dict[str, List[str]] = {}
    for ev in eventos:
        d = ev["data"]
        if d not in dias_com_eventos:
            dias_com_eventos[d] = []
        if ev["cor"] not in dias_com_eventos[d]:
            dias_com_eventos[d].append(ev["cor"])

    # Eventos de hoje
    hoje_str = hoje.strftime("%Y-%m-%d")
    eventos_hoje = [e for e in eventos if e["data"] == hoje_str]

    return {
        "ano": alvo_ano,
        "mes": alvo_mes,
        "mes_nome": NOMES_MESES[alvo_mes],
        "total_eventos": len(eventos),
        "total_hoje": len(eventos_hoje),
        "eventos_hoje": eventos_hoje,
        "dias_com_eventos": dias_com_eventos,
        "eventos": eventos,
    }


async def obter_proximos_eventos(
    session: AsyncSession,
    limite: int = 8,
    dias_a_frente: int = 60
) -> Dict[str, Any]:
    """Retorna os próximos compromissos cronológicos a partir de hoje num horizonte configurável (Saúde, Veículos, Pessoal)."""
    hoje = date.today()
    fim_horizonte = hoje + timedelta(days=dias_a_frente)
    eventos: List[Dict[str, Any]] = []

    # 1. Consultas de Saúde (hoje até fim_horizonte)
    try:
        res = await session.execute(text("""
            SELECT c.id, c.data_hora, c.especialidade, c.medico, c.local_clinica, t.nome as paciente
            FROM consulta_medica c
            JOIN perfil_saude p ON p.id = c.perfil_id
            JOIN titular t ON t.id = p.titular_id
            WHERE c.data_hora::date BETWEEN :inicio AND :fim
            ORDER BY c.data_hora ASC;
        """), {"inicio": hoje, "fim": fim_horizonte})
        for r in res.mappings():
            dt = r["data_hora"]
            eventos.append({
                "id": f"saude-{r['id']}",
                "origem_id": str(r["id"]),
                "titulo": f"Consulta: {r['especialidade']}",
                "subtitulo": f"{r['paciente']} • {r['local_clinica'] or ''} {('- ' + r['medico']) if r['medico'] else ''}".strip(),
                "data": dt.strftime("%Y-%m-%d"),
                "hora": dt.strftime("%H:%M") if hasattr(dt, "strftime") else "00:00",
                "tipo": "saude",
                "cor": "rose",
                "icone": "stethoscope",
                "local": r["local_clinica"] or "",
                "origem": "saude",
                "editavel": True,
            })
    except Exception as e:
        print(f"Erro ao recolher consultas para próximos eventos: {e}")

    # 2. Veículos: Próxima IPO (hoje até fim_horizonte)
    try:
        res = await session.execute(text("""
            SELECT id, nome, matricula, data_proxima_ipo
            FROM veiculo
            WHERE ativo = true AND data_proxima_ipo BETWEEN :inicio AND :fim
            ORDER BY data_proxima_ipo ASC;
        """), {"inicio": hoje, "fim": fim_horizonte})
        for r in res.mappings():
            dt = r["data_proxima_ipo"]
            eventos.append({
                "id": f"veiculo-ipo-{r['id']}",
                "origem_id": str(r["id"]),
                "titulo": f"Inspeção IPO: {r['nome']}",
                "subtitulo": f"Plate {r['matricula'] or '—'}",
                "data": dt.strftime("%Y-%m-%d"),
                "hora": "09:00",
                "tipo": "veiculo",
                "cor": "emerald",
                "icone": "car",
                "local": "Centro de Inspeções",
                "origem": "veiculos",
                "editavel": False,
            })
    except Exception as e:
        print(f"Erro ao recolher veículos para próximos eventos: {e}")

    # 3. Eventos Pessoais & Familiares (hoje até fim_horizonte)
    try:
        res = await session.execute(text("""
            SELECT id, titulo, descricao, data_inicio, tipo, local
            FROM evento_calendario
            WHERE data_inicio::date BETWEEN :inicio AND :fim
            ORDER BY data_inicio ASC;
        """), {"inicio": hoje, "fim": fim_horizonte})
        for r in res.mappings():
            dt = r["data_inicio"]
            eventos.append({
                "id": str(r["id"]),
                "origem_id": str(r["id"]),
                "titulo": r["titulo"],
                "subtitulo": r["local"] or r["descricao"] or "",
                "data": dt.strftime("%Y-%m-%d"),
                "hora": dt.strftime("%H:%M") if hasattr(dt, "strftime") else "00:00",
                "tipo": r["tipo"] or "pessoal",
                "cor": "violet",
                "icone": "calendar",
                "local": r["local"] or "",
                "origem": "pessoal",
                "editavel": True,
            })
    except Exception as e:
        print(f"Erro ao recolher eventos pessoais para próximos eventos: {e}")

    # 4. Google Calendar (iCal Privado)
    try:
        from hub.config import get_settings
        from hub.services.google_calendar_service import obter_eventos_google_calendar
        settings = get_settings()
        if settings.google_calendar_ical_url:
            g_events = await obter_eventos_google_calendar(settings.google_calendar_ical_url)
            ignorados = await obter_ids_ignorados(session)
            hoje_s = hoje.strftime("%Y-%m-%d")
            fim_s = fim_horizonte.strftime("%Y-%m-%d")
            for ge in g_events:
                if ge["id"] in ignorados or ge.get("origem_id") in ignorados:
                    continue
                if hoje_s <= ge["data"] <= fim_s:
                    ja_existe_consulta = any(
                        e.get("tipo") == "saude" and e.get("data") == ge["data"]
                        for e in eventos
                    )
                    if not ja_existe_consulta:
                        eventos.append(ge)
    except Exception as e:
        print(f"Erro ao recolher Google Calendar para próximos eventos: {e}")

    # Ordenação cronológica
    eventos.sort(key=lambda x: (x["data"], x["hora"]))

    # Eventos de hoje
    hoje_str = hoje.strftime("%Y-%m-%d")
    eventos_hoje = [e for e in eventos if e["data"] == hoje_str]

    return {
        "total_eventos": len(eventos),
        "total_hoje": len(eventos_hoje),
        "eventos_hoje": eventos_hoje,
        "eventos": eventos[:limite],
    }


async def criar_evento_calendario(session: AsyncSession, dados: Dict[str, Any]) -> Dict[str, Any]:
    """Cria um novo evento pessoal ou consulta médica na agenda."""
    tipo = dados.get("tipo", "pessoal")
    if tipo == "saude":
        paciente = dados.get("paciente", "aa-stop-run")
        res_perfil = await session.execute(text("""
            SELECT p.id as perfil_id, t.nome
            FROM titular t
            JOIN perfil_saude p ON p.titular_id = t.id
            WHERE t.nome ILIKE :nome
            LIMIT 1;
        """), {"nome": f"%{paciente}%"})
        mappings = res_perfil.mappings()
        row = mappings.first() if hasattr(mappings, "first") else (mappings[0] if mappings else None)
        if not row:
            res_def = await session.execute(text("""
                SELECT p.id as perfil_id, t.nome
                FROM titular t
                JOIN perfil_saude p ON p.titular_id = t.id
                ORDER BY t.tipo ASC
                LIMIT 1;
            """))
            mappings_def = res_def.mappings()
            row = mappings_def.first() if hasattr(mappings_def, "first") else (mappings_def[0] if mappings_def else None)

        perfil_id = row["perfil_id"] if row else uuid.uuid4()
        consulta_id = uuid.uuid4()
        especialidade = dados.get("titulo", "").replace("Consulta: ", "").strip() or "Medicina Geral"
        await session.execute(text("""
            INSERT INTO consulta_medica (
                id, perfil_id, data_hora, especialidade, medico, local_clinica,
                motivo, custo, concluida, criado_em
            ) VALUES (
                :id, :perfil_id, :data_hora, :especialidade, :medico, :local_clinica,
                :motivo, 0.00, false, NOW()
            );
        """), {
            "id": consulta_id,
            "perfil_id": perfil_id,
            "data_hora": dados["data_inicio"],
            "especialidade": especialidade,
            "medico": dados.get("medico", ""),
            "local_clinica": dados.get("local", ""),
            "motivo": dados.get("descricao", "Criado via Agenda Cockpit"),
        })
        await session.commit()
        return {
            "id": f"saude-{consulta_id}",
            "titulo": f"Consulta: {especialidade}",
            "data_inicio": str(dados["data_inicio"]),
            "tipo": "saude",
            "local": dados.get("local", "")
        }

    res = await session.execute(text("""
        INSERT INTO evento_calendario (titulo, descricao, data_inicio, data_fim, tipo, local, notificar)
        VALUES (:titulo, :descricao, :data_inicio, :data_fim, :tipo, :local, :notificar)
        RETURNING id, titulo, descricao, data_inicio, tipo, local;
    """), {
        "titulo": dados["titulo"],
        "descricao": dados.get("descricao", ""),
        "data_inicio": dados["data_inicio"],
        "data_fim": dados.get("data_fim"),
        "tipo": tipo,
        "local": dados.get("local", ""),
        "notificar": dados.get("notificar", True),
    })
    await session.commit()
    row = res.mappings().first()
    return dict(row)


async def atualizar_evento_calendario(
    session: AsyncSession,
    evento_id: str,
    dados: Dict[str, Any]
) -> Dict[str, Any]:
    """Atualiza um evento pessoal ou uma consulta médica na agenda."""
    limpo_id = evento_id
    if evento_id.startswith("saude-"):
        limpo_id = evento_id.replace("saude-", "")
        especialidade = dados.get("titulo")
        if especialidade and especialidade.startswith("Consulta: "):
            especialidade = especialidade.replace("Consulta: ", "")

        await session.execute(text("""
            UPDATE consulta_medica
            SET especialidade = COALESCE(:especialidade, especialidade),
                data_hora = COALESCE(:data_hora, data_hora),
                local_clinica = COALESCE(:local, local_clinica),
                medico = COALESCE(:medico, medico)
            WHERE id = CAST(:id AS uuid);
        """), {
            "id": limpo_id,
            "especialidade": especialidade,
            "data_hora": dados.get("data_inicio"),
            "local": dados.get("local"),
            "medico": dados.get("medico"),
        })
        await session.commit()
        return {"id": evento_id, "status": "atualizado", "origem": "saude"}

    # Tenta atualizar em evento_calendario
    try:
        res = await session.execute(text("""
            UPDATE evento_calendario
            SET titulo = COALESCE(:titulo, titulo),
                descricao = COALESCE(:descricao, descricao),
                data_inicio = COALESCE(:data_inicio, data_inicio),
                local = COALESCE(:local, local)
            WHERE id = CAST(:id AS uuid);
        """), {
            "id": limpo_id,
            "titulo": dados.get("titulo"),
            "descricao": dados.get("descricao"),
            "data_inicio": dados.get("data_inicio"),
            "local": dados.get("local"),
        })
        if (res.rowcount or 0) > 0:
            await session.commit()
            return {"id": evento_id, "status": "atualizado", "origem": "pessoal"}
    except Exception:
        pass

    # Se não atualizou, tenta em consulta_medica com uuid direto
    try:
        especialidade = dados.get("titulo")
        if especialidade and especialidade.startswith("Consulta: "):
            especialidade = especialidade.replace("Consulta: ", "")

        res_saude = await session.execute(text("""
            UPDATE consulta_medica
            SET especialidade = COALESCE(:especialidade, especialidade),
                data_hora = COALESCE(:data_hora, data_hora),
                local_clinica = COALESCE(:local, local_clinica),
                medico = COALESCE(:medico, medico)
            WHERE id = CAST(:id AS uuid);
        """), {
            "id": limpo_id,
            "especialidade": especialidade,
            "data_hora": dados.get("data_inicio"),
            "local": dados.get("local"),
            "medico": dados.get("medico"),
        })
        if (res_saude.rowcount or 0) > 0:
            await session.commit()
            return {"id": evento_id, "status": "atualizado", "origem": "saude"}
    except Exception:
        pass

    raise ValueError("Evento não encontrado para atualização.")


async def remover_evento_calendario(session: AsyncSession, evento_id: str) -> bool:
    """Remove um evento da agenda pessoal, desmarca consulta médica ou oculta evento do Google Calendar."""
    limpo_id = evento_id
    
    # Se for evento do Google Calendar, adiciona à blacklist de ignorados na app (mantém no Google)
    if evento_id.startswith("google-") or evento_id.startswith("gcal-"):
        await _garantir_tabela_ignorados(session)
        await session.execute(text("""
            INSERT INTO evento_calendario_ignorado (id)
            VALUES (:id)
            ON CONFLICT (id) DO NOTHING;
        """), {"id": evento_id})
        await session.commit()
        return True

    if evento_id.startswith("saude-"):
        limpo_id = evento_id.replace("saude-", "")
        res = await session.execute(text("""
            DELETE FROM consulta_medica WHERE id = CAST(:id AS uuid);
        """), {"id": limpo_id})
        await session.commit()
        return (res.rowcount or 0) > 0

    # Tenta remover de evento_calendario
    try:
        res = await session.execute(text("""
            DELETE FROM evento_calendario WHERE id = CAST(:id AS uuid);
        """), {"id": limpo_id})
        if (res.rowcount or 0) > 0:
            await session.commit()
            return True
    except Exception:
        pass

    # Se não removeu, tenta de consulta_medica
    try:
        res_saude = await session.execute(text("""
            DELETE FROM consulta_medica WHERE id = CAST(:id AS uuid);
        """), {"id": limpo_id})
        if (res_saude.rowcount or 0) > 0:
            await session.commit()
            return True
    except Exception:
        pass

    return False


async def gerar_feed_ical_ava(session: AsyncSession) -> str:
    """Gera um ficheiro iCal (.ics) padronizado RFC 5545 com os eventos internos da AVA (saúde, pessoais, veículos)."""
    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//AVA Personal Assistant//PT",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:AVA Assistente Pessoal",
        "X-WR-TIMEZONE:Europe/Lisbon",
    ]

    # 1. Eventos pessoais
    try:
        res = await session.execute(text("""
            SELECT id, titulo, descricao, data_inicio, data_fim, local
            FROM evento_calendario
            ORDER BY data_inicio ASC;
        """))
        for r in res.mappings():
            dt_ini = r["data_inicio"]
            dt_fim = r["data_fim"] or (dt_ini + timedelta(hours=1))
            dt_ini_str = dt_ini.strftime("%Y%m%dT%H%M%SZ") if hasattr(dt_ini, "strftime") else ""
            dt_fim_str = dt_fim.strftime("%Y%m%dT%H%M%SZ") if hasattr(dt_fim, "strftime") else ""
            summary = (r["titulo"] or "Compromisso").replace("\n", " ").replace(",", "\\,")
            desc = (r["descricao"] or "").replace("\n", "\\n").replace(",", "\\,")
            loc = (r["local"] or "").replace("\n", " ").replace(",", "\\,")

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:ava-pessoal-{r['id']}@ava.local",
                f"DTSTAMP:{now_utc}",
                f"DTSTART:{dt_ini_str}",
                f"DTEND:{dt_fim_str}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{desc}",
                f"LOCATION:{loc}",
                "END:VEVENT",
            ])
    except Exception as e:
        print(f"Erro ao recolher eventos pessoais para iCal: {e}")

    # 2. Consultas de Saúde
    try:
        res = await session.execute(text("""
            SELECT c.id, c.data_hora, c.especialidade, c.medico, c.local_clinica, t.nome as paciente
            FROM consulta_medica c
            JOIN perfil_saude p ON p.id = c.perfil_id
            JOIN titular t ON t.id = p.titular_id
            ORDER BY c.data_hora ASC;
        """))
        for r in res.mappings():
            dt_ini = r["data_hora"]
            dt_fim = dt_ini + timedelta(hours=1)
            dt_ini_str = dt_ini.strftime("%Y%m%dT%H%M%SZ") if hasattr(dt_ini, "strftime") else ""
            dt_fim_str = dt_fim.strftime("%Y%m%dT%H%M%SZ") if hasattr(dt_fim, "strftime") else ""
            summary = f"Consulta: {r['especialidade']} ({r['paciente']})".replace(",", "\\,")
            desc = f"Paciente: {r['paciente']}\\nMédico: {r['medico'] or 'N/A'}\\nLocal: {r['local_clinica'] or 'N/A'}".replace(",", "\\,")
            loc = (r["local_clinica"] or "").replace("\n", " ").replace(",", "\\,")

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:ava-saude-{r['id']}@ava.local",
                f"DTSTAMP:{now_utc}",
                f"DTSTART:{dt_ini_str}",
                f"DTEND:{dt_fim_str}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{desc}",
                f"LOCATION:{loc}",
                "END:VEVENT",
            ])
    except Exception as e:
        print(f"Erro ao recolher consultas para iCal: {e}")

    # 3. Veículos (IPOs)
    try:
        res = await session.execute(text("""
            SELECT id, nome, matricula, data_proxima_ipo
            FROM veiculo
            WHERE ativo = true AND data_proxima_ipo IS NOT NULL;
        """))
        for r in res.mappings():
            dt_ipo = r["data_proxima_ipo"]
            d_str = dt_ipo.strftime("%Y%m%d")
            summary = f"Inspeção IPO: {r['nome']} ({r['matricula'] or '—'})".replace(",", "\\,")

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:ava-veiculo-{r['id']}@ava.local",
                f"DTSTAMP:{now_utc}",
                f"DTSTART;VALUE=DATE:{d_str}",
                f"SUMMARY:{summary}",
                "DESCRIPTION:Inspeção periódica obrigatória",
                "LOCATION:Centro de Inspeções",
                "END:VEVENT",
            ])
    except Exception as e:
        print(f"Erro ao recolher veículos para iCal: {e}")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
