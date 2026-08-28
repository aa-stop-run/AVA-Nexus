import pathlib
from datetime import date
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from casa.db import get_session
from casa.repositories import casa_repo

router = APIRouter()

templates_dir = pathlib.Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.get("/", response_class=HTMLResponse)
async def dashboard_casa(request: Request, session: AsyncSession = Depends(get_session)):
    equipamentos = await casa_repo.obter_equipamentos(session)
    manutencoes = await casa_repo.obter_manutencoes(session)

    total_eq = len(equipamentos)
    garantias_ativas = sum(1 for e in equipamentos if e.estado_garantia in ["em_garantia", "a_expirar"])
    garantias_a_expirar = sum(1 for e in equipamentos if e.estado_garantia == "a_expirar")
    total_manut = len(manutencoes)

    return templates.TemplateResponse(
        request,
        "casa.html",
        {
            "equipamentos": equipamentos,
            "manutencoes": manutencoes,
            "total_equipamentos": total_eq,
            "garantias_ativas": garantias_ativas,
            "garantias_a_expirar": garantias_a_expirar,
            "total_manutencoes": total_manut,
        },
    )


@router.get("/api/casa/resumo")
async def resumo_casa(session: AsyncSession = Depends(get_session)):
    """Resumo para widget do AVA Hub Cockpit."""
    equipamentos = await casa_repo.obter_equipamentos(session)
    manutencoes = await casa_repo.obter_manutencoes(session)

    a_expirar = [
        {"nome": e.nome, "dias": e.dias_restantes_garantia, "data_fim": str(e.data_fim_garantia)}
        for e in equipamentos if e.estado_garantia == "a_expirar"
    ]
    prox_manut = [
        {"titulo": m.titulo, "proxima_data": str(m.proxima_data), "divisao": m.divisao_casa}
        for m in manutencoes if m.proxima_data
    ]

    return {
        "total_equipamentos": len(equipamentos),
        "garantias_ativas": sum(1 for e in equipamentos if e.estado_garantia in ["em_garantia", "a_expirar"]),
        "garantias_a_expirar_count": len(a_expirar),
        "garantias_a_expirar": a_expirar,
        "proximas_manutencoes": prox_manut[:3],
    }


@router.post("/api/casa/equipamentos")
async def adicionar_equipamento(
    nome: str = Form(...),
    marca: Optional[str] = Form(None),
    modelo: Optional[str] = Form(None),
    numero_serie: Optional[str] = Form(None),
    categoria: str = Form("eletronica"),
    divisao_casa: str = Form("Geral"),
    data_compra: Optional[date] = Form(None),
    valor_compra: Optional[Decimal] = Form(None),
    fornecedor_loja: Optional[str] = Form(None),
    anos_garantia: int = Form(3),
    session: AsyncSession = Depends(get_session),
):
    await casa_repo.criar_equipamento(
        session,
        nome=nome,
        marca=marca,
        modelo=modelo,
        numero_serie=numero_serie,
        categoria=categoria,
        divisao_casa=divisao_casa,
        data_compra=data_compra,
        valor_compra=valor_compra,
        fornecedor_loja=fornecedor_loja,
        anos_garantia=anos_garantia,
    )
    return RedirectResponse(url="/", status_code=303)


@router.post("/api/casa/manutencoes")
async def adicionar_manutencao(
    titulo: str = Form(...),
    divisao_casa: str = Form("Geral"),
    periodicidade_meses: int = Form(12),
    proxima_data: Optional[date] = Form(None),
    custo_estimado: Optional[Decimal] = Form(None),
    tecnico_contacto: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session),
):
    await casa_repo.criar_manutencao(
        session,
        titulo=titulo,
        divisao_casa=divisao_casa,
        periodicidade_meses=periodicidade_meses,
        proxima_data=proxima_data,
        custo_estimado=custo_estimado,
        tecnico_contacto=tecnico_contacto,
    )
    return RedirectResponse(url="/", status_code=303)
