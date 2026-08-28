import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from worker.worker import loop_principal, processar_um_item

FATURA_VALIDA = {
    "fornecedor_nome": "Fornecedor Desconhecido, Lda",
    "nif_emissor": "502011475",
    "iban": "PT50000201231234567890154",
    "valor_total": "38.20",
    "data_limite_pagamento": "2026-08-10",
    "linhas": [],
    "consumo": None,
}


@pytest.mark.asyncio
async def test_processar_um_item_submete_resultado_quando_llm_responde_com_fatura_valida():
    fila = AsyncMock()
    fila.obter_proximo.return_value = {"item_id": "abc-123", "texto_ocr": "texto da fatura", "tipo": "fatura"}
    llm = AsyncMock()
    llm.chat_completion_json.return_value = FATURA_VALIDA

    houve_trabalho = await processar_um_item(fila, llm)

    assert houve_trabalho is True
    fila.submeter_erro.assert_not_awaited()
    fila.submeter_resultado.assert_awaited_once()
    item_id, resultado = fila.submeter_resultado.await_args.args
    assert item_id == "abc-123"
    assert resultado["fornecedor_nome"] == "Fornecedor Desconhecido, Lda"
    assert Decimal(str(resultado["valor_total"])) == Decimal("38.20")


@pytest.mark.asyncio
async def test_processar_um_item_submete_erro_quando_llm_responde_fora_do_esquema():
    fila = AsyncMock()
    fila.obter_proximo.return_value = {"item_id": "abc-123", "texto_ocr": "texto da fatura", "tipo": "fatura"}
    llm = AsyncMock()
    llm.chat_completion_json.return_value = {"isto": "não é uma fatura"}

    houve_trabalho = await processar_um_item(fila, llm)

    assert houve_trabalho is True
    fila.submeter_resultado.assert_not_awaited()
    fila.submeter_erro.assert_awaited_once()
    item_id, mensagem = fila.submeter_erro.await_args.args
    assert item_id == "abc-123"
    assert "valor_total" in mensagem or "fornecedor_nome" in mensagem


@pytest.mark.asyncio
async def test_processar_um_item_submete_erro_quando_llm_falha():
    fila = AsyncMock()
    fila.obter_proximo.return_value = {"item_id": "abc-123", "texto_ocr": "texto da fatura", "tipo": "fatura"}
    llm = AsyncMock()
    llm.chat_completion_json.side_effect = RuntimeError("timeout do modelo")

    houve_trabalho = await processar_um_item(fila, llm)

    assert houve_trabalho is True
    fila.submeter_erro.assert_awaited_once_with("abc-123", "timeout do modelo")
    fila.submeter_resultado.assert_not_awaited()


@pytest.mark.asyncio
async def test_processar_um_item_devolve_false_quando_fila_vazia():
    fila = AsyncMock()
    fila.obter_proximo.return_value = None
    llm = AsyncMock()

    houve_trabalho = await processar_um_item(fila, llm)

    assert houve_trabalho is False
    llm.chat_completion_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_loop_principal_sobrevive_a_falha_e_continua_para_proxima_iteracao(monkeypatch):
    # 1ª iteração: obter_proximo falha (ex.: instabilidade transitória de rede) — nem sequer
    #   chega ao try/except interno de processar_um_item, tem de ser apanhada pelo loop.
    # 2ª iteração: processamento normal com uma fatura válida, deve continuar a acontecer.
    # 3ª iteração: CancelledError (BaseException, não Exception) usada só para parar o
    #   `while True` no teste, sem ser apanhada pelos `except Exception` do código.
    fila = AsyncMock()
    fila.obter_proximo.side_effect = [
        RuntimeError("falha transitória ao consultar a fila"),
        {"item_id": "abc-123", "texto_ocr": "texto da fatura", "tipo": "fatura"},
        asyncio.CancelledError(),
    ]
    llm = AsyncMock()
    llm.chat_completion_json.return_value = FATURA_VALIDA

    sleep_mock = AsyncMock()
    monkeypatch.setattr("worker.worker.asyncio.sleep", sleep_mock)

    with pytest.raises(asyncio.CancelledError):
        await loop_principal(fila, llm)

    assert fila.obter_proximo.await_count == 3
    fila.submeter_resultado.assert_awaited_once()
    sleep_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_processar_um_item_submete_resultado_para_extrato_bancario():
    fila = AsyncMock()
    fila.obter_proximo.return_value = {
        "item_id": "ext-001",
        "texto_ocr": "texto do extrato",
        "tipo": "extrato_bancario",
    }
    llm = AsyncMock()
    llm.chat_completion_json.return_value = {
        "instituicao": "CGD",
        "tipo_conta": "a_ordem",
        "nome_conta": "Conta à Ordem",
        "saldo_final": {"data": "2026-07-31", "valor": "1350.00"},
        "movimentos": [{"data": "2026-07-01", "valor": "-45.67", "descricao": "DD EDP"}],
    }

    houve_trabalho = await processar_um_item(fila, llm)

    assert houve_trabalho is True
    fila.submeter_erro.assert_not_awaited()
    item_id, resultado = fila.submeter_resultado.await_args.args
    assert item_id == "ext-001"
    assert resultado["instituicao"] == "CGD"


