import re
import uuid
from datetime import datetime, date, time, timedelta, timezone
from typing import Optional, Dict, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


NOMES_MESES = {
    "janeiro": 1, "jan": 1,
    "fevereiro": 2, "fev": 2,
    "março": 3, "marco": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "maio": 5, "mai": 5,
    "junho": 6, "jun": 6,
    "julho": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "setembro": 9, "set": 9,
    "outubro": 10, "out": 10,
    "novembro": 11, "nov": 11,
    "dezembro": 12, "dez": 12,
}

NOMES_MESES_EXTENSO = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}

ESPECIALIDADES = [
    "pediatria", "oftalmologia", "dermatologia", "cardiologia",
    "ortopedia", "ginecologia", "obstetrícia", "dentista",
    "estomatologia", "medicina geral", "clínica geral", "psiquiatria",
    "psicologia", "nutrição", "fisioterapia", "análises", "exames",
    "urologia", "otorrino", "neurologia", "gastroenterologia"
]


def extrair_data_hora(texto: str, data_base: Optional[date] = None) -> Optional[datetime]:
    """Extrai data e hora de uma string de comando em linguagem natural."""
    t = texto.lower()
    hoje = data_base or date.today()
    data_encontrada = None
    hora_encontrada = time(9, 0)

    # 1. Padrões relativos de dias
    if "hoje" in t:
        data_encontrada = hoje
    elif "depois de amanhã" in t or "depois de amanha" in t:
        data_encontrada = hoje + timedelta(days=2)
    elif "amanhã" in t or "amanha" in t:
        data_encontrada = hoje + timedelta(days=1)
    
    # 2. Padrões de dias da semana
    dias_semana = {
        "segunda": 0, "segunda-feira": 0,
        "terça": 1, "terca": 1, "terça-feira": 1, "terca-feira": 1,
        "quarta": 2, "quarta-feira": 2,
        "quinta": 3, "quinta-feira": 3,
        "sexta": 4, "sexta-feira": 4,
        "sábado": 5, "sabado": 5,
        "domingo": 6
    }
    if not data_encontrada:
        for ds, num in dias_semana.items():
            if re.search(rf"\b{ds}\b", t):
                dias_a_somar = (num - hoje.weekday()) % 7
                if dias_a_somar == 0:
                    dias_a_somar = 7
                data_encontrada = hoje + timedelta(days=dias_a_somar)
                break

    # 3. Padrões numéricos
    if not data_encontrada:
        m_data = re.search(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b", t)
        if m_data:
            dia = int(m_data.group(1))
            mes = int(m_data.group(2))
            ano = int(m_data.group(3)) if m_data.group(3) else hoje.year
            if ano < 100:
                ano += 2000
            try:
                data_encontrada = date(ano, mes, dia)
            except ValueError:
                pass
        
        if not data_encontrada:
            m_mes = re.search(r"\b(?:dia\s+)?(\d{1,2})\s+(?:de\s+)?([a-zçã]+)(?:\s+(?:de\s+)?(\d{4}))?\b", t)
            if m_mes:
                dia = int(m_mes.group(1))
                nome_mes = m_mes.group(2)
                ano = int(m_mes.group(3)) if m_mes.group(3) else hoje.year
                if nome_mes in NOMES_MESES:
                    mes = NOMES_MESES[nome_mes]
                    try:
                        data_encontrada = date(ano, mes, dia)
                    except ValueError:
                        pass
        
        if not data_encontrada:
            m_dia = re.search(r"\bdia\s+(\d{1,2})\b", t)
            if m_dia:
                dia = int(m_dia.group(1))
                mes = hoje.month
                ano = hoje.year
                if dia < hoje.day:
                    mes += 1
                    if mes > 12:
                        mes = 1
                        ano += 1
                try:
                    data_encontrada = date(ano, mes, dia)
                except ValueError:
                    pass

    if not data_encontrada:
        return None

    # 4. Extração de Hora
    m_hora = re.search(r"\b(?:às|as|pelas|para\s+as|para\s+às)\s+(\d{1,2})(?::(\d{2})|h(\d{2})|h)?\b", t)
    if m_hora:
        h = int(m_hora.group(1))
        m = int(m_hora.group(2) or m_hora.group(3) or 0)
        if 0 <= h <= 23 and 0 <= m <= 59:
            hora_encontrada = time(h, m)
    else:
        m_hora2 = re.search(r"\b(\d{1,2}):(\d{2})\b", t)
        if m_hora2:
            h = int(m_hora2.group(1))
            m = int(m_hora2.group(2))
            if 0 <= h <= 23 and 0 <= m <= 59:
                hora_encontrada = time(h, m)
        else:
            m_hora3 = re.search(r"\b(\d{1,2})h(?:(\d{2}))?\b", t)
            if m_hora3:
                h = int(m_hora3.group(1))
                m = int(m_hora3.group(2) or 0)
                if 0 <= h <= 23 and 0 <= m <= 59:
                    hora_encontrada = time(h, m)
            else:
                if "jantar" in t:
                    hora_encontrada = time(20, 0)
                elif "almoço" in t or "almoco" in t:
                    hora_encontrada = time(13, 0)

    dt_final = datetime.combine(data_encontrada, hora_encontrada).replace(tzinfo=timezone.utc)
    return dt_final


def extrair_entidades_consulta(texto: str) -> Optional[Dict[str, Any]]:
    """Extrai os campos de uma marcação de consulta médica."""
    t = texto.strip()
    tl = t.lower()
    
    # 1. Determinar paciente (Junior, Member, aa-stop-run)
    paciente = "aa-stop-run"
    if re.search(r"\b(para\s+o\s+)?junior\b|\bcharlie\b|\bfilho\b|\bmiúdo\b|\bmiudo\b|\bpediatria\b", tl):
        paciente = "Junior"
    elif re.search(r"\b(para\s+a\s+)?member\b|\bsam\b|\besposa\b|\bmulher\b", tl):
        paciente = "Member"
    elif re.search(r"\b(para\s+o\s+)?aa-stop-run\b|\balex\b|\bpara\s+mim\b", tl):
        paciente = "aa-stop-run"

    # 2. Determinar especialidade médica
    especialidade = "Medicina Geral"
    for esp in ESPECIALIDADES:
        if esp in tl:
            especialidade = esp.capitalize()
            break
            
    m_esp = re.search(r"\bconsulta\s+de\s+([a-zA-ZÀ-ÿ]+)", tl)
    if m_esp and m_esp.group(1) not in ["rotina", "urgência", "urgencia"]:
        palavra = m_esp.group(1)
        if len(palavra) > 3:
            especialidade = palavra.capitalize()

    # 3. Determinar médico
    medico = None
    m_med = re.search(r"\bcom\s+(?:o\s+|a\s+)?((?:dr[a]?\.|doutor[a]?|médico|medica)?\s*[a-zA-ZÀ-ÿ]+(?:\s+[a-zA-ZÀ-ÿ]+)?)", t, re.IGNORECASE)
    if m_med:
        cand = m_med.group(1).strip()
        if not any(w in cand.lower() for w in ["dia", "hora", "hospital", "clínica"]):
            medico = cand

    # 4. Determinar local / clínica
    local = None
    m_loc = re.search(r"\b(?:na|no|em|at)\s+((?:cuf|hospital|clínica|clinica|centro de saúde|posto médico|medical center|clinic)[^,\.\n]*?)(?=\s+com\b|\s+às\b|\s+as\b|\s+dia\b|\.|\n|$)", tl)
    if m_loc:
        cand_loc = m_loc.group(1).strip()
        local = cand_loc.upper() if cand_loc.lower() == "cuf" else cand_loc.title()
    elif "cuf" in tl:
        local = "CUF"

    # 5. Extrair data e hora
    dt = extrair_data_hora(t)
    if not dt:
        return None

    return {
        "tipo": "saude",
        "paciente": paciente,
        "especialidade": especialidade,
        "medico": medico,
        "local_clinica": local,
        "data_hora": dt,
    }


def extrair_entidades_evento(texto: str) -> Optional[Dict[str, Any]]:
    """Extrai os campos de um compromisso pessoal ou evento geral de calendário."""
    t = texto.strip()
    tl = t.lower()

    dt = extrair_data_hora(t)
    if not dt:
        return None

    local = None
    m_loc = re.search(r"\b(?:no|na|em|at)\s+((?:restaurante|café|bar|hotel|hospital|clínica|clinica|aeroporto|parque|quinta|pavilhão)[^,\.\n]+)", t, re.IGNORECASE)
    if m_loc:
        local = m_loc.group(1).strip()
    else:
        m_loc_gen = re.search(r"\b(?:no|na|em|at)\s+([a-zA-ZÀ-ÿ0-9\s.-]+?)(?=\s+(?:às|as|dia|amanhã|amanha|hoje|pelas|para)|$)", t, re.IGNORECASE)
        if m_loc_gen:
            cand = m_loc_gen.group(1).strip()
            if cand.lower() not in ["casa", "calendário", "calendario", "agenda", "mim", "família", "familia"] and len(cand) > 2:
                local = cand.title()

    titulo_cand = re.sub(r"^\s*(?:marca|marcar|agendar|aponta|apontar|adiciona|adicionar|anota|anotar|registar|regista|agenda)\s+", "", t, flags=re.IGNORECASE)
    titulo_cand = re.sub(r"\b(?:amanhã|amanha|hoje|depois de amanhã|segunda-feira|terça-feira|quarta-feira|quinta-feira|sexta-feira|sábado|domingo)", "", titulo_cand, flags=re.IGNORECASE)
    titulo_cand = re.sub(r"\b(?:às|as|pelas)\s+\d{1,2}(?::\d{2}|h\d{2}|h)?", "", titulo_cand, flags=re.IGNORECASE)
    if local:
        titulo_cand = re.sub(rf"\b(?:no|na|em)\s+{re.escape(local)}", "", titulo_cand, flags=re.IGNORECASE)

    titulo_limpo = " ".join(titulo_cand.split()).strip(" ,.-")
    if not titulo_limpo or len(titulo_limpo) < 3:
        if "jantar" in tl:
            titulo_limpo = "Jantar em Família"
        elif "almoço" in tl or "almoco" in tl:
            titulo_limpo = "Almoço"
        elif "reunião" in tl or "reuniao" in tl:
            titulo_limpo = "Reunião"
        elif "aniversário" in tl or "aniversario" in tl or "anos" in tl:
            titulo_limpo = "Festa de Aniversário"
        else:
            titulo_limpo = "Compromisso Familiar"

    return {
        "tipo": "pessoal",
        "titulo": titulo_limpo.capitalize(),
        "local": local or "Lisboa",
        "data_hora": dt,
    }


async def tentar_agendar_por_texto(query: str, session: AsyncSession) -> Optional[str]:
    """Tenta detetar intenção de marcação e efetua o registo determinístico imediato na base de dados."""
    q = query.strip()
    ql = q.lower()

    inquiricoes = [
        "o que", "o q", "quais", "qual", "quando", "quanto", "onde", "como",
        "tens", "tenho", "temos", "ver", "mostra", "mostrar", "consultar",
        "pesquisa", "pesquisar", "diz-me", "diz me", "explica"
    ]
    if any(ql.startswith(i) for i in inquiricoes) or ql.endswith("?"):
        return None

    padrao_gatilho = r"\b(marca|marcar|agendar|aponta|apontar|adiciona|adicionar|anota|anotar|registar|regista)\b"
    e_comando = bool(re.search(padrao_gatilho, ql))
    
    if not e_comando and re.search(r"\bagenda\b", ql):
        if not re.search(r"\b(na|da|minha|nossa|tua)\s+agenda\b", ql):
            e_comando = True
            
    if not e_comando:
        if any(ql.startswith(k) for k in ["consulta ", "revisão ", "revisao ", "jantar ", "almoço ", "almoco "]) and any(d in ql for d in ["dia ", "amanhã", "amanha", "hoje", "às ", "as "]):
            e_comando = True

    if not e_comando:
        return None

    palavras_saude = ["consulta", "médic", "medic", "dentista", "pediatr", "oftalmolog", "dermatolog", "exame", "análise", "analise", "vacina"]
    e_saude = any(p in ql for p in palavras_saude)

    if e_saude:
        dados = extrair_entidades_consulta(q)
        if not dados:
            return None

        res_perfil = await session.execute(text("""
            SELECT p.id as perfil_id, t.nome
            FROM titular t
            JOIN perfil_saude p ON p.titular_id = t.id
            WHERE t.nome ILIKE :nome
            LIMIT 1;
        """), {"nome": f"%{dados['paciente']}%"})
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
        paciente_nome = row["nome"] if row else dados["paciente"]

        consulta_id = uuid.uuid4()
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
            "data_hora": dados["data_hora"],
            "especialidade": dados["especialidade"],
            "medico": dados["medico"],
            "local_clinica": dados["local_clinica"],
            "motivo": f"Agendado via AVA Cockpit por voz/texto: {dados['especialidade']}",
        })
        if hasattr(session, "commit"):
            await session.commit()

        dt = dados["data_hora"]
        data_str = f"{dt.day} de {NOMES_MESES_EXTENSO.get(dt.month, '')}"
        hora_str = dt.strftime("%H:%M")
        local_str = f" na **{dados['local_clinica']}**" if dados["local_clinica"] else ""
        medico_str = f" com **{dados['medico']}**" if dados["medico"] else ""

        return (
            f"Marquei a consulta de **{dados['especialidade']}** para o **{paciente_nome}** "
            f"no dia **{data_str}** às **{hora_str}**{local_str}{medico_str}. "
            f"Já está registada na tua base de dados e visível no painel da Agenda."
        )

    dados_ev = extrair_entidades_evento(q)
    if not dados_ev:
        return None

    evento_id = uuid.uuid4()
    await session.execute(text("""
        INSERT INTO evento_calendario (
            id, titulo, descricao, data_inicio, tipo, local, notificar, created_at, updated_at
        ) VALUES (
            :id, :titulo, :descricao, :data_inicio, :tipo, :local, true, NOW(), NOW()
        );
    """), {
        "id": evento_id,
        "titulo": dados_ev["titulo"],
        "descricao": f"Compromisso criado via assistente AVA: {dados_ev['titulo']}",
        "data_inicio": dados_ev["data_hora"],
        "tipo": "pessoal",
        "local": dados_ev["local"],
    })
    if hasattr(session, "commit"):
        await session.commit()

    dt = dados_ev["data_hora"]
    data_str = f"{dt.day} de {NOMES_MESES_EXTENSO.get(dt.month, '')}"
    hora_str = dt.strftime("%H:%M")
    local_str = f" em **{dados_ev['local']}**" if dados_ev["local"] else ""

    return (
        f"Agendei **{dados_ev['titulo']}** para o dia **{data_str}** "
        f"às **{hora_str}**{local_str}. Já podes consultar no painel da tua Agenda."
    )
