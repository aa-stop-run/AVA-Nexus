import json

from ava.extraction.schema import FaturaExtraida

SYSTEM_PROMPT_FATURA = """\
Extrai os dados desta fatura portuguesa e devolve APENAS um objeto JSON com \
exatamente estes campos (usa null quando não aplicável):

{schema}

Datas no formato AAAA-MM-DD. Valores monetários como número decimal (não incluas o símbolo €). \
Se a fatura indicar um consumo medido (eletricidade em kWh ou água em m³) com um período de \
faturação, preenche "consumo"; caso contrário usa null.\
"""


def construir_prompt_sistema() -> str:
    esquema = json.dumps(FaturaExtraida.model_json_schema(), ensure_ascii=False, indent=2)
    return SYSTEM_PROMPT_FATURA.format(schema=esquema)


def validar_resposta(resposta_json: dict) -> FaturaExtraida:
    return FaturaExtraida.model_validate(resposta_json)
