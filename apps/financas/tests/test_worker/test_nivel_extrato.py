from ava.extraction.schema_extrato import ExtratoBancario
from worker.nivel_extrato import construir_prompt_extrato, validar_resposta_extrato


def test_construir_prompt_extrato_inclui_esquema_json():
    prompt = construir_prompt_extrato()

    assert "instituicao" in prompt
    assert "movimentos" in prompt


def test_construir_prompt_extrato_exclui_campo_interno_linhas_nao_reconhecidas():
    prompt = construir_prompt_extrato()

    # Verify the parser-internal diagnostic field is excluded from the prompt
    assert "linhas_nao_reconhecidas" not in prompt

    # Verify real content fields are still present
    assert "instituicao" in prompt
    assert "movimentos" in prompt
    assert "saldo_final" in prompt


def test_validar_resposta_extrato_aceita_json_valido():
    resposta = {
        "instituicao": "CGD",
        "tipo_conta": "a_ordem",
        "nome_conta": "Conta à Ordem",
        "saldo_final": {"data": "2026-07-31", "valor": "1350.00"},
        "movimentos": [],
    }

    extrato = validar_resposta_extrato(resposta)

    assert isinstance(extrato, ExtratoBancario)
    assert extrato.instituicao == "CGD"
