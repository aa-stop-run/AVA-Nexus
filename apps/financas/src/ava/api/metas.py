import uuid
from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ava.api.shared import templates, _contar_alertas
from ava.db import get_session
from ava.financas.metas import calcular_progresso_meta
from ava.repositories import conta_repo, meta_poupanca_repo

router = APIRouter(tags=["metas"])


@router.get("/metas", response_class=HTMLResponse)
async def listar_metas_page(
    request: Request, session: AsyncSession = Depends(get_session)
):
    metas = await meta_poupanca_repo.listar_metas(session)
    hoje = date.today()
    progressos = [calcular_progresso_meta(m, hoje=hoje) for m in metas]

    total_alvo = sum((m.valor_alvo for m in metas), Decimal("0.00"))
    total_atual = sum((m.valor_atual for m in metas), Decimal("0.00"))
    pct_global = (
        (total_atual / total_alvo * Decimal("100.0")).quantize(Decimal("0.01"))
        if total_alvo > 0
        else Decimal("0.00")
    )
    if pct_global > Decimal("100.0"):
        pct_global = Decimal("100.0")

    todas_contas = await conta_repo.listar_todas_ativas(session)
    contas_poupanca = [
        c
        for c in todas_contas
        if c.tipo in ("poupanca", "investimento", "certificados", "a_ordem")
    ]

    total_alertas = await _contar_alertas(session)

    return templates.TemplateResponse(
        request,
        "metas.html",
        {
            "metas": metas,
            "progressos": progressos,
            "total_alvo": total_alvo,
            "total_atual": total_atual,
            "pct_global": pct_global,
            "contas_poupanca": contas_poupanca,
            "total_alertas": total_alertas,
        },
    )


@router.post("/metas")
async def criar_meta_route(
    request: Request,
    nome: str = Form(...),
    valor_alvo: Decimal = Form(...),
    valor_atual: Decimal = Form(Decimal("0.00")),
    data_alvo: date | None = Form(None),
    conta_id: uuid.UUID | None = Form(None),
    descricao: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    await meta_poupanca_repo.criar_meta(
        session,
        nome=nome,
        valor_alvo=valor_alvo,
        valor_atual=valor_atual,
        data_alvo=data_alvo,
        conta_id=conta_id,
        descricao=descricao,
    )
    await session.commit()
    return RedirectResponse(url="/metas", status_code=303)


@router.post("/metas/{meta_id}/ajustar-saldo", response_class=HTMLResponse)
async def ajustar_saldo_meta_route(
    meta_id: uuid.UUID,
    request: Request,
    delta: Decimal | None = Form(None),
    novo_valor: Decimal | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    meta = await meta_poupanca_repo.ajustar_valor_atual(
        session, meta_id=meta_id, delta=delta, novo_valor=novo_valor
    )
    if meta is None:
        raise HTTPException(status_code=404, detail="meta não encontrada")

    await session.commit()
    prog = calcular_progresso_meta(meta)
    return templates.TemplateResponse(
        request,
        "_meta_card.html",
        {"p": prog},
    )


@router.post("/metas/{meta_id}/apagar")
async def apagar_meta_route(
    meta_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    removido = await meta_poupanca_repo.remover_meta(session, meta_id)
    if not removido:
        raise HTTPException(status_code=404, detail="meta não encontrada")

    await session.commit()
    if request.headers.get("HX-Request"):
        return HTMLResponse(content="")
    return RedirectResponse(url="/metas", status_code=303)
