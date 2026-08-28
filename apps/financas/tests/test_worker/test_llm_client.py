import httpx
import pytest
import respx

from worker.llm_client import LLMClient


@pytest.mark.asyncio
@respx.mock
async def test_chat_completion_json_extrai_conteudo_da_resposta():
    respx.post("http://desktop.local/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"valor_total": "45.67"}'}}]},
        )
    )

    client = LLMClient(base_url="http://desktop.local")
    resultado = await client.chat_completion_json(system_prompt="sistema", user_prompt="texto")
    await client.aclose()

    assert resultado == {"valor_total": "45.67"}
