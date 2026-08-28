import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


@dataclass
class MarcacaoExtraida:
    tipo: str  # consulta | exame
    nome_paciente: str | None
    especialidade: str
    data_hora: datetime
    medico: str | None = None
    local_clinica: str | None = None
    motivo: str | None = None
    preparacao_instrucoes: str | None = None
    codigo_confirmacao: str | None = None
    custo: Decimal = Decimal("0.00")


MEMBROS_CONHECIDOS = ["Junior", "Member", "aa-stop-run"]


def extrair_marcacao_saude(texto: str) -> MarcacaoExtraida | None:
    """Extrai informações estruturadas de agendamento de consultas ou exames de texto de email."""
    if not texto:
        return None

    texto_clean = texto.replace("\r", "")

    # 1. Identifica o Membro Familiar / Paciente
    nome_paciente = None
    for membro in MEMBROS_CONHECIDOS:
        if re.search(r"\b" + re.escape(membro) + r"\b", texto_clean, re.IGNORECASE):
            nome_paciente = membro
            break

    # 2. Identifica Data e Hora
    # Formatos comuns: DD/MM/YYYY às HH:MM ou DD-MM-YYYY ou YYYY-MM-DD
    match_data_hora = re.search(
        r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\s+(?:às|as)?\s*(\d{1,2}):(\d{2})",
        texto_clean,
        re.IGNORECASE,
    )
    if not match_data_hora:
        # Tenta data e hora separadas
        match_data = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", texto_clean)
        match_hora = re.search(r"(?:às|as)?\s*(\d{1,2}):(\d{2})", texto_clean)
        if match_data and match_hora:
            dia, mes, ano = map(int, match_data.groups())
            hora, minuto = map(int, match_hora.groups())
            data_hora = datetime(ano, mes, dia, hora, minuto, tzinfo=timezone.utc)
        else:
            return None
    else:
        dia, mes, ano, hora, minuto = map(int, match_data_hora.groups())
        data_hora = datetime(ano, mes, dia, hora, minuto, tzinfo=timezone.utc)

    # 3. Identifica se é Consulta ou Exame
    eh_exame = bool(re.search(r"\b(exame|análises|analises|ecografia|raio-x|tac|ressonância|ressonancia)\b", texto_clean, re.IGNORECASE))
    tipo = "exame" if eh_exame else "consulta"

    # 4. Especialidade / Tipo de Ato
    especialidade = "Consulta Geral"
    match_esp = re.search(
        r"(?:consulta|exame)\s+de\s+([A-Za-zÀ-ÿ\s/]+?)(?=\s+(?:com|no|dia|às|em|\.|\n))",
        texto_clean,
        re.IGNORECASE,
    )
    if match_esp:
        especialidade = match_esp.group(1).strip()
    elif eh_exame:
        especialidade = "Análises Clínicas"

    # 5. Médico
    medico = None
    match_med = re.search(
        r"(?:com\s+(?:o\(a\)|o/a|a|o)?\s*|Médico:\s*|Medica:\s*)(?:Dr\(a\)\.?|Drª?\.?|Dr\.?|Dra\.?)?\s*([A-Za-zÀ-ÿ\s]+?)(?=\s+(?:no|na|dia|às|as|\.|\n))",
        texto_clean,
        re.IGNORECASE,
    )
    if match_med:
        medico = match_med.group(1).strip()

    # 6. Local / Clínica / Hospital
    local_clinica = None
    match_loc = re.search(r"(?:Local:\s*|Location:\s*|Clinic:\s*|Clínica:\s*|(?:no|na|em|at)\s+)(Hospital[^\n\.]+|Clínica[^\n\.]+|Clinic[^\n\.]+|Centro de Saúde[^\n\.]+|Medical Center[^\n\.]+)", texto_clean, re.IGNORECASE)
    if match_loc:
        local_clinica = match_loc.group(1).strip()

    # 7. Código de confirmação
    codigo_confirmacao = None
    match_cod = re.search(
        r"(?:código(?:\s+de\s+marcação)?|codigo|referência|ref\.?)[\s\w]*?:\s*([A-Z0-9-]+)",
        texto_clean,
        re.IGNORECASE,
    )
    if match_cod:
        codigo_confirmacao = match_cod.group(1).strip()

    # 8. Recomendações / Jejum / Preparação
    preparacao = None
    match_prep = re.search(r"(?:recomendações|recomendacoes|instruções|instrucoes|preparação|preparacao)[\s:]*([^\n.]+)", texto_clean, re.IGNORECASE)
    if match_prep:
        preparacao = match_prep.group(1).strip()

    return MarcacaoExtraida(
        tipo=tipo,
        nome_paciente=nome_paciente,
        especialidade=especialidade,
        data_hora=data_hora,
        medico=medico,
        local_clinica=local_clinica,
        preparacao_instrucoes=preparacao,
        codigo_confirmacao=codigo_confirmacao,
    )
