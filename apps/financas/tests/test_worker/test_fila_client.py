import json

import httpx
import pytest
import respx

from worker.worker import FilaClient

BASE_URL = "http://desktop.local"
TOKEN = "token-secreto-123"


@pytest.mark.asyncio
@respx.mock
async def test_obter_proximo_devolve_dict_quando_200_com_json():
    respx.get(f"{BASE_URL}/api/fila/proximo").mock(
        return_value=httpx.Response(
            200,
            json={"item_id": "abc-123", "texto_ocr": "texto da fatura"},
        )
    )

    client = FilaClient(base_url=BASE_URL, token=TOKEN)
    item = await client.obter_proximo()
    await client.aclose()

    assert item == {"item_id": "abc-123", "texto_ocr": "texto da fatura"}


@pytest.mark.asyncio
@respx.mock
async def test_obter_proximo_devolve_none_quando_204():
    respx.get(f"{BASE_URL}/api/fila/proximo").mock(return_value=httpx.Response(204))

    client = FilaClient(base_url=BASE_URL, token=TOKEN)
    item = await client.obter_proximo()
    await client.aclose()

    assert item is None


@pytest.mark.asyncio
@respx.mock
async def test_obter_proximo_envia_header_authorization_bearer():
    rota = respx.get(f"{BASE_URL}/api/fila/proximo").mock(return_value=httpx.Response(204))

    client = FilaClient(base_url=BASE_URL, token=TOKEN)
    await client.obter_proximo()
    await client.aclose()

    assert rota.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.asyncio
@respx.mock
async def test_submeter_resultado_faz_post_com_corpo_correto():
    rota = respx.post(f"{BASE_URL}/api/fila/abc-123/resultado").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    client = FilaClient(base_url=BASE_URL, token=TOKEN)
    await client.submeter_resultado("abc-123", {"valor_total": "45.67"})
    await client.aclose()

    assert rota.called
    assert rota.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(rota.calls.last.request.content) == {"resultado": {"valor_total": "45.67"}}


@pytest.mark.asyncio
@respx.mock
async def test_submeter_erro_faz_post_com_corpo_correto():
    rota = respx.post(f"{BASE_URL}/api/fila/abc-123/erro").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    client = FilaClient(base_url=BASE_URL, token=TOKEN)
    await client.submeter_erro("abc-123", "timeout do modelo")
    await client.aclose()

    assert rota.called
    assert rota.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(rota.calls.last.request.content) == {"mensagem": "timeout do modelo"}
