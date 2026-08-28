from decimal import Decimal, InvalidOperation
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ava.api.shared import templates, _contar_alertas
from ava.db import get_session
from ava.financas.simulador_credito import calcular_amortizacao
from ava.repositories import conta_repo, saldo_historico_repo

router = APIRouter(tags=["simulador"])


@router.get("/simulador", response_class=HTMLResponse)
async def simulador_page(request: Request, session: AsyncSession = Depends(get_session)):
    contas = await conta_repo.listar_todas_ativas(session)
    contas_divida = []
    capital_inicial = Decimal("150000.00")

    for c in contas:
        if c.tipo == "divida":
            saldo_deriv = await saldo_historico_repo.saldo_derivado(session, c)
            val = saldo_deriv.valor if saldo_deriv is not None else Decimal("0.00")
            contas_divida.append({"conta": c, "saldo": val})
            if val > 0:
                capital_inicial = val

    res = calcular_amortizacao(
        capital_atual=capital_inicial,
        taxa_anual=Decimal("3.50"),
        prazo_meses=300,
        valor_amortizar=Decimal("5000.00"),
        taxa_comissao=Decimal("0.5"),
    )

    total_alertas = await _contar_alertas(session)

    return templates.TemplateResponse(
        request,
        "simulador.html",
        {
            "contas_divida": contas_divida,
            "capital_inicial": capital_inicial,
            "res": res,
            "total_alertas": total_alertas,
        },
    )


@router.post("/simulador/calcular", response_class=HTMLResponse)
async def simulador_calcular(
    request: Request,
    capital_divida: str = Form(...),
    taxa_anual: str = Form(...),
    prazo_meses: int = Form(...),
    valor_amortizar: str = Form(...),
    taxa_comissao: str = Form("0.5"),
):
    try:
        cap = Decimal(capital_divida.replace(",", "."))
        taxa = Decimal(taxa_anual.replace(",", "."))
        amort = Decimal(valor_amortizar.replace(",", "."))
        comiss = Decimal(taxa_comissao.replace(",", "."))
        res = calcular_amortizacao(
            capital_atual=cap,
            taxa_anual=taxa,
            prazo_meses=prazo_meses,
            valor_amortizar=amort,
            taxa_comissao=comiss,
        )
    except (InvalidOperation, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    return templates.TemplateResponse(
        request,
        "_simulador_resultados.html",
        {"res": res},
    )
