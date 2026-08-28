import json
from decimal import Decimal
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ava.api.shared import templates, _contar_alertas
from ava.db import get_session
from ava.financas.tesouraria import calcular_projecao_tesouraria

router = APIRouter(tags=["tesouraria"])


@router.get("/tesouraria", response_class=HTMLResponse)
async def tesouraria_page(request: Request, session: AsyncSession = Depends(get_session)):
    """Apresenta a previsão de liquidez e tesouraria familiar a 30/60/90 dias."""
    proj = await calcular_projecao_tesouraria(session, dias_projecao=90)
    total_alertas = await _contar_alertas(session)

    # Preparar dados para o gráfico Chart.js
    chart_labels = [p.data.strftime("%d/%m") for p in proj.pontos_diarios]
    chart_values = [float(p.saldo_estimado) for p in proj.pontos_diarios]
    chart_entradas = [float(p.entradas) for p in proj.pontos_diarios]
    chart_saidas = [float(p.saidas) for p in proj.pontos_diarios]

    return templates.TemplateResponse(
        request,
        "tesouraria.html",
        {
            "proj": proj,
            "chart_labels": json.dumps(chart_labels),
            "chart_values": json.dumps(chart_values),
            "chart_entradas": json.dumps(chart_entradas),
            "chart_saidas": json.dumps(chart_saidas),
            "total_alertas": total_alertas,
        },
    )
