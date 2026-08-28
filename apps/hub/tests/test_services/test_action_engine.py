import pytest
from unittest.mock import AsyncMock, MagicMock
from decimal import Decimal
from hub.services.action_engine import tentar_executar_acao
from hub.services.conversation_memory import conversation_memory


@pytest.mark.asyncio
async def test_tentar_executar_acao_apagar_veiculo_nivel_2():
    # Mock da sessão SQL
    session = AsyncMock()
    # Simular veículo encontrado
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = {
        "id": "f1d23d65-0f5f-4b94-837d-614c958bd198",
        "nome": "Sedan 2.0 TDI",
        "matricula": "AA-01-BB",
        "km_atual": 168000,
    }
    session.execute.return_value = mock_result

    # Passo 1: Ordem para apagar veículo
    res = await tentar_executar_acao("apaga o renault megane com a matrícula aa-01-bb", session, session_id="test_del")
    assert res is not None
    assert res.get("aguarda_confirmacao") is True
    assert "⚠️ Tens a certeza" in res["resposta_texto"]
    assert "**Sedan 2.0 TDI** (AA-01-BB)" in res["resposta_texto"]
    assert len(res["actions"]) == 2  # Botão Confirm e Cancel

    # Verificar que ficou gravado na memória como pending_action
    ctx = conversation_memory.get_session("test_del")
    assert ctx.pending_action is not None
    assert ctx.pending_action["type"] == "apagar_veiculo"

    # Passo 2: Utilizador diz "Sim" para confirmar
    res_confirm = await tentar_executar_acao("Sim", session, session_id="test_del")
    assert res_confirm is not None
    assert res_confirm.get("sucesso") is True
    assert "foi permanentemente removido" in res_confirm["resposta_texto"]
    assert ctx.pending_action is None


@pytest.mark.asyncio
async def test_tentar_executar_acao_abastecimento():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = {
        "id": "7627bd42-3beb-4f5f-9cec-2ab1ddd015d5",
        "nome": "Sedan 2.0 TDI",
        "matricula": "AA-01-BB",
        "km_atual": 170000,
    }
    session.execute.return_value = mock_result

    query = "regista 45 litros de gasóleo no mégane por 72 euros a 170.500 km"
    res = await tentar_executar_acao(query, session, session_id="test_fuel")
    assert res is not None
    assert res.get("sucesso") is True
    assert "Abastecimento Registado" in res["resposta_texto"]
    assert "45.00 L" in res["resposta_texto"]
    assert "€ 72.00" in res["resposta_texto"]
    assert "170,500 km" in res["resposta_texto"]

    # Deve conter botão de Desfazer
    action_types = [a["type"] for a in res["actions"]]
    assert "btn_query" in action_types
