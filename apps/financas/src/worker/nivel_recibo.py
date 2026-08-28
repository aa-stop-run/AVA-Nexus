import json
from ava.extraction.schema_recibo import ReciboVencimentoExtraido

def construir_prompt_recibo() -> str:
    schema = ReciboVencimentoExtraido.model_json_schema()
    return (
        "És um assistente focado em extração de dados.\n"
        "O utilizador vai enviar o texto OCR de um recibo de vencimento (payslip).\n"
        "A tua única tarefa é extrair 4 campos específicos desse recibo e devolver um objeto JSON válido.\n\n"
        "O teu output deve ser APENAS o JSON, com a seguinte estrutura exata:\n"
        "{\n"
        '  "cartao_refeicao": "valor decimal do subsídio de alimentação",\n'
        '  "entidade_patronal": "nome da empresa",\n'
        '  "mes_referencia": numero_do_mes,\n'
        '  "ano_referencia": numero_do_ano\n'
        "}\n\n"
        "Não incluas o texto original. Não incluas chaves adicionais como 'texto' ou 'recibo'."
    )

def validar_resposta_recibo(resposta: dict) -> ReciboVencimentoExtraido:
    return ReciboVencimentoExtraido.model_validate(resposta)
