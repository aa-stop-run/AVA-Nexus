import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from veiculos.api.shared import templates
from veiculos.db import get_session
from veiculos.logica.prazos_ipo import calcular_proxima_ipo, verificar_estado_prazos
from veiculos.logica.consumos import calcular_medias_abastecimentos, AbastecimentoInput
from veiculos.repositories import veiculo_repo

router = APIRouter(tags=["garagem"])


@router.get("/")
async def garagem_page(request: Request, session: AsyncSession = Depends(get_session)):
    hoje = date.today()
    veiculos = await veiculo_repo.listar_veiculos(session)

    veiculos_cards = []
    total_km_frota = 0
    total_gasto_manutencoes = Decimal("0.00")
    total_alertas = 0

    for v in veiculos:
        total_km_frota += v.km_atual
        
        # Prazos e Alertas
        data_ipo = v.data_proxima_ipo or calcular_proxima_ipo(
            ano_matricula=v.ano_matricula,
            mes_matricula=v.mes_matricula,
            tipo=v.tipo,
            referencia=hoje,
        )
        estado = verificar_estado_prazos(
            data_proxima_ipo=data_ipo,
            mes_matricula_iuc=v.mes_matricula,
            data_fim_seguro=v.data_fim_seguro,
            hoje=hoje,
        )

        if estado["ipo_alerta"] or estado["iuc_mes_atual"] or estado["seguro_alerta"]:
            total_alertas += 1

        # Consumo Médio
        abast_inputs = [
            AbastecimentoInput(
                data=ab.data,
                km=ab.km,
                quantidade=ab.quantidade,
                preco_total=ab.preco_total,
                tanque_cheio=ab.tanque_cheio,
            )
            for ab in v.abastecimentos
        ]
        stats_consumo = calcular_medias_abastecimentos(abast_inputs)

        # Gastos em Maintenance
        gasto_v_manut = sum((m.custo for m in v.manutencoes), Decimal("0.00"))
        total_gasto_manutencoes += gasto_v_manut

        veiculos_cards.append(
            {
                "veiculo": v,
                "data_proxima_ipo": data_ipo,
                "estado_prazos": estado,
                "consumo_medio": stats_consumo["consumo_medio_geral"],
                "total_manutencoes": len(v.manutencoes),
                "gasto_total_manutencoes": gasto_v_manut,
            }
        )

    return templates.TemplateResponse(
        request,
        "garagem.html",
        {
            "veiculos_cards": veiculos_cards,
            "total_km_frota": total_km_frota,
            "total_gasto_manutencoes": total_gasto_manutencoes,
            "total_alertas": total_alertas,
        },
    )


@router.post("/veiculos")
async def criar_veiculo_post(
    request: Request,
    nome: str = Form(...),
    tipo: str = Form("carro"),
    matricula: str | None = Form(None),
    ano_matricula: int | None = Form(None),
    mes_matricula: int | None = Form(None),
    combustivel: str = Form("gasoleo"),
    km_atual: int = Form(0),
    data_proxima_ipo: date | None = Form(None),
    seguradora: str | None = Form(None),
    numero_apolice: str | None = Form(None),
    data_fim_seguro: date | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    await veiculo_repo.criar_veiculo(
        session,
        nome=nome,
        tipo=tipo,
        matricula=matricula,
        ano_matricula=ano_matricula,
        mes_matricula=mes_matricula,
        combustivel=combustivel,
        km_atual=km_atual,
        data_proxima_ipo=data_proxima_ipo,
        seguradora=seguradora,
        numero_apolice=numero_apolice,
        data_fim_seguro=data_fim_seguro,
    )
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/veiculos/{id}/atualizar-km")
async def atualizar_km_post(
    request: Request,
    id: uuid.UUID,
    novo_km: int = Form(...),
    session: AsyncSession = Depends(get_session),
):
    v = await veiculo_repo.atualizar_km(session, id, novo_km)
    if "HX-Request" in request.headers:
        return templates.TemplateResponse(
            request,
            "_km_badge.html",
            {"veiculo": v},
        )
    return RedirectResponse(f"/veiculos/{id}", status_code=status.HTTP_303_SEE_OTHER)
