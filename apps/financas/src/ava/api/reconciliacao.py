"""A página que mostra onde o razão não explica o saldo.

Nada aqui é gravado a não ser as dispensas: a lista é recalculada a cada pedido, para se curar
sozinha quando o movimento em falta for classificado (spec §10).
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from ava.api.dashboard import _contar_alertas, format_pt
from ava.db import get_session
from ava.models.divergencia_aceite import DivergenciaAceite
from ava.repositories import divergencia_repo, documento_repo

router = APIRouter(tags=["reconciliacao"])
templates = Jinja2Templates(directory="src/ava/templates")
templates.env.filters["format_pt"] = format_pt


@router.get("/reconciliacao", response_class=HTMLResponse)
async def reconciliacao_get(request: Request, session: AsyncSession = Depends(get_session)):
    return templates.TemplateResponse(
        request,
        "reconciliacao.html",
        {
            "divergencias": await divergencia_repo.listar_divergencias(session),
            "por_confirmar": await divergencia_repo.listar_por_confirmar_antigos(session),
            "total_alertas": await _contar_alertas(session),
            # 30 dias: um extrato é mensal, por isso a janela mostra sempre a última ingestão de
            # cada conta sem encher a página com o histórico todo.
            "importados": await documento_repo.listar_com_resumo_de_ingestao(
                session, desde=date.today() - timedelta(days=30)
            ),
        },
    )


@router.post("/reconciliacao/dispensar")
async def dispensar(
    conta_id: uuid.UUID = Form(...),
    data: str = Form(...),
    valor: str = Form(...),
    motivo: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    """Marca uma divergência como "não vale a pena perseguir".

    É o único estado guardado da reconciliação. Sem isto, uma divergência que nunca vai ser
    resolvida — um extrato perdido — ficaria a incomodar para sempre.

    Dispensar a mesma janela duas vezes (duplo clique, ou voltar atrás e reenviar o formulário) é
    inócuo: a unicidade é `(conta_id, data)`, por isso atualiza a dispensa existente em vez de
    tentar inserir outra — o mesmo padrão que `registar_saldo_manual` (configuracoes.py) já usa
    para a âncora manual. Sem isto, o segundo pedido rebentava com `IntegrityError` não tratado
    e devolvia 500.
    """
    try:
        data_janela = date.fromisoformat(data.strip())
        valor_dec = Decimal(valor.replace(",", ".").strip())
    except (ValueError, InvalidOperation):
        raise HTTPException(status_code=400, detail="data ou valor inválidos")

    existente = await divergencia_repo.obter_dispensa(session, conta_id, data_janela)
    if existente is not None:
        existente.motivo = motivo.strip()
        existente.valor = valor_dec
    else:
        session.add(
            DivergenciaAceite(
                conta_id=conta_id, data=data_janela, valor=valor_dec, motivo=motivo.strip()
            )
        )
    await session.commit()
    return RedirectResponse(url="/reconciliacao", status_code=303)
