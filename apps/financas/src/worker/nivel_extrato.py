import json

from ava.extraction.schema_extrato import ExtratoBancario

SYSTEM_PROMPT_EXTRATO = """\
Extrai os dados deste extrato bancário e devolve APENAS um objeto JSON com \
exatamente estes campos (usa null quando não aplicável):

{schema}

Datas no formato AAAA-MM-DD. Valores monetários como número decimal, com sinal: \
positivo para entradas, negativo para saídas. Inclui TODOS os movimentos listados no extrato, \
não resumas nem omitas nenhum.\
"""


def construir_prompt_extrato() -> str:
    schema = ExtratoBancario.model_json_schema()
    # Exclude parser-internal field from the prompt schema: the LLM has no way to meaningfully
    # compute this diagnostic, and showing it would implicitly ask it to invent a value.
    schema['properties'].pop('linhas_nao_reconhecidas', None)
    if 'required' in schema and 'linhas_nao_reconhecidas' in schema['required']:
        schema['required'].remove('linhas_nao_reconhecidas')

    esquema = json.dumps(schema, ensure_ascii=False, indent=2)
    return SYSTEM_PROMPT_EXTRATO.format(schema=esquema)


def validar_resposta_extrato(resposta_json: dict) -> ExtratoBancario:
    return ExtratoBancario.model_validate(resposta_json)
