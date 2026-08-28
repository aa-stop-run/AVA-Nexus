import asyncio
import logging
import os

import httpx

from worker.llm_client import LLMClient
from worker.nivel1 import construir_prompt_sistema, validar_resposta, FaturaExtraida
from worker.nivel_extrato import construir_prompt_extrato, validar_resposta_extrato, ExtratoBancario
from worker.nivel_recibo import construir_prompt_recibo, validar_resposta_recibo, ReciboVencimentoExtraido

logger = logging.getLogger("ava.worker")

POLL_INTERVAL_SECONDS = 5.0

ESQUEMAS_POR_TIPO = {
    "fatura": (construir_prompt_sistema, validar_resposta, FaturaExtraida),
    "extrato_bancario": (construir_prompt_extrato, validar_resposta_extrato, ExtratoBancario),
    "recibo_vencimento": (construir_prompt_recibo, validar_resposta_recibo, ReciboVencimentoExtraido),
}


class FilaClient:
    def __init__(self, base_url: str, token: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

    async def obter_proximo(self) -> dict | None:
        response = await self._client.get("/api/fila/proximo")
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return response.json()

    async def submeter_resultado(self, item_id: str, resultado: dict) -> None:
        response = await self._client.post(f"/api/fila/{item_id}/resultado", json={"resultado": resultado})
        response.raise_for_status()

    async def submeter_erro(self, item_id: str, mensagem: str) -> None:
        response = await self._client.post(f"/api/fila/{item_id}/erro", json={"mensagem": mensagem})
        response.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()


async def processar_um_item(fila: FilaClient, llm: LLMClient) -> bool:
    item = await fila.obter_proximo()
    if item is None:
        return False

    construir_prompt, validar, modelo = ESQUEMAS_POR_TIPO.get(item["tipo"], ESQUEMAS_POR_TIPO["fatura"])

    try:
        resposta = await llm.chat_completion_json(
            system_prompt=construir_prompt(), 
            user_prompt=item["texto_ocr"],
            schema=modelo.model_json_schema()
        )
        resultado = validar(resposta)
        await fila.submeter_resultado(item["item_id"], resultado.model_dump(mode="json"))
    except Exception as exc:  # noqa: BLE001 — qualquer falha tem de chegar ao servidor, nunca em silêncio (A-P6)
        logger.exception("falha ao estruturar item %s", item["item_id"])
        await fila.submeter_erro(item["item_id"], str(exc))

    return True


async def loop_principal(fila: FilaClient, llm: LLMClient) -> None:
    while True:
        try:
            houve_trabalho = await processar_um_item(fila, llm)
        except Exception:  # noqa: BLE001 — nenhuma falha pode derrubar o worker (A-P6)
            logger.exception("falha inesperada no ciclo do worker — a continuar")
            houve_trabalho = False
        if not houve_trabalho:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    fila = FilaClient(base_url=os.environ["SERVIDOR_URL"], token=os.environ["WORKER_SHARED_TOKEN"])
    llm = LLMClient(base_url=os.environ["LLM_BASE_URL"])
    asyncio.run(loop_principal(fila, llm))


if __name__ == "__main__":
    main()
