import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ava.api.auth import verificar_token_worker
from ava.api.deps import get_paperless_client
from ava.db import get_session
from ava.ingestion import pipeline
from ava.integrations.paperless import PaperlessClient
from ava.repositories import fila_repo

router = APIRouter(prefix="/api/fila", tags=["fila"], dependencies=[Depends(verificar_token_worker)])


class ItemProximo(BaseModel):
    item_id: uuid.UUID
    texto_ocr: str
    tipo: str


class ResultadoPayload(BaseModel):
    resultado: dict


class ErroPayload(BaseModel):
    mensagem: str


@router.get("/proximo", response_model=ItemProximo | None)
async def obter_proximo(session: AsyncSession = Depends(get_session)):
    item = await fila_repo.obter_proximo_pendente(session)
    if item is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    await fila_repo.marcar_em_processamento(session, item.id)
    await session.commit()
    return ItemProximo(item_id=item.id, texto_ocr=item.texto_ocr, tipo=item.tipo)


@router.post("/{item_id}/resultado", status_code=status.HTTP_204_NO_CONTENT)
async def submeter_resultado(
    item_id: uuid.UUID,
    payload: ResultadoPayload,
    session: AsyncSession = Depends(get_session),
    paperless: PaperlessClient = Depends(get_paperless_client),
) -> None:
    item = await fila_repo.obter_por_id(session, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="item não encontrado")
    if item.estado == "finalizado":
        # retry idempotente: o item já foi processado numa chamada anterior. concluir()
        # reescreveria estado para "concluido", destruindo o próprio sinal que o guard de
        # finalizar_extrato_nivel1 depende — por isso o corte tem de acontecer aqui, antes
        # de qualquer chamada a concluir() (Critical — ver task-15-report.md).
        return
    await fila_repo.concluir(session, item_id, payload.resultado)
    await session.commit()

    if item.tipo == "extrato_bancario":
        await pipeline.finalizar_extrato_nivel1(
            session, item_id=item_id, paperless=paperless, referencia=date.today()
        )
    elif item.tipo == "recibo_vencimento":
        await pipeline.finalizar_recibo_vencimento(
            session, item_id=item_id, paperless=paperless, referencia=date.today()
        )
    else:
        await pipeline.finalizar_documento_nivel1(
            session, item_id=item_id, paperless=paperless, referencia=date.today()
        )


@router.post("/{item_id}/erro", status_code=status.HTTP_204_NO_CONTENT)
async def submeter_erro(
    item_id: uuid.UUID, payload: ErroPayload, session: AsyncSession = Depends(get_session)
) -> None:
    item = await fila_repo.obter_por_id(session, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="item não encontrado")
    await fila_repo.marcar_erro(session, item_id, payload.mensagem)
    await session.commit()
