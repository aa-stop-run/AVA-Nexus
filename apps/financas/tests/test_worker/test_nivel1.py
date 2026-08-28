import pytest
from pydantic import ValidationError

from ava.extraction.schema import FaturaExtraida
from worker.nivel1 import construir_prompt_sistema, validar_resposta


def test_construir_prompt_sistema_inclui_o_esquema_json():
    prompt = construir_prompt_sistema()

    assert "fornecedor_nome" in prompt
    assert "valor_total" in prompt
    assert "AAAA-MM-DD" in prompt


def test_validar_resposta_aceita_json_valido():
    resposta = {
        "fornecedor_nome": "MEO",
        "nif_emissor": None,
        "iban": None,
        "valor_total": "29.99",
        "data_limite_pagamento": "2026-08-05",
        "linhas": [],
        "consumo": None,
    }

    fatura = validar_resposta(resposta)

    assert isinstance(fatura, FaturaExtraida)
    assert fatura.fornecedor_nome == "MEO"


def test_validar_resposta_rejeita_json_incompleto():
    with pytest.raises(ValidationError):
        validar_resposta({"isto": "não é uma fatura"})
