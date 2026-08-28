import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ava.api.deps import get_paperless_client
from ava.api.shared import _contar_alertas, templates
from ava.db import get_session
from ava.ingestion.pipeline import aprovar_documento_manualmente
from ava.integrations.paperless import PaperlessClient
from ava.repositories import documento_repo, fila_repo, obrigacao_repo

router = APIRouter(tags=["alertas"])


@router.get("/revisao")
async def revisao(request: Request, session: AsyncSession = Depends(get_session)):
    documentos = await documento_repo.listar_por_estado(session, "revisao_manual")
    return templates.TemplateResponse(
        request,
        "revisao.html",
        {"documentos": documentos, "total_alertas": await _contar_alertas(session)},
    )


@router.post("/revisao/{documento_id}/aprovar", response_class=HTMLResponse)
async def aprovar_revisao(
    documento_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    paperless: PaperlessClient = Depends(get_paperless_client),
):
    aprovado = await aprovar_documento_manualmente(
        session, documento_id=documento_id, paperless=paperless
    )
    if not aprovado:
        raise HTTPException(
            status_code=404, detail="documento não encontrado ou já processado"
        )
    return templates.TemplateResponse(request, "revisao_linha_aprovada.html", {})


@router.get("/falhas")
async def falhas(request: Request, session: AsyncSession = Depends(get_session)):
    itens = await fila_repo.listar_com_erro(session)
    return templates.TemplateResponse(
        request,
        "falhas.html",
        {"itens": itens, "total_alertas": await _contar_alertas(session)},
    )


@router.get("/alertas")
async def alertas(request: Request, session: AsyncSession = Depends(get_session)):
    documentos = await documento_repo.listar_por_estado(session, "revisao_manual")
    obrigacoes_raw = await obrigacao_repo.listar_pendentes(session)
    hoje = date.today()
    obrigacoes = [
        {"obrigacao": o, "dias_restantes": (o.data_limite - hoje).days}
        for o in obrigacoes_raw
    ]
    falhas_lista = await fila_repo.listar_com_erro(session)
    total = len(documentos) + len(obrigacoes) + len(falhas_lista)
    return templates.TemplateResponse(
        request,
        "alertas.html",
        {
            "documentos": documentos,
            "obrigacoes": obrigacoes,
            "falhas": falhas_lista,
            "total_alertas": total,
        },
    )
