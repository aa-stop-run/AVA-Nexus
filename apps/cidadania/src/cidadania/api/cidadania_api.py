import pathlib
from datetime import date
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from cidadania.db import get_session
from cidadania.repositories import cidadania_repo

router = APIRouter()

templates_dir = pathlib.Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


@router.get("/", response_class=HTMLResponse)
async def dashboard_cidadania(request: Request, session: AsyncSession = Depends(get_session)):
    documentos = await cidadania_repo.obter_documentos(session)
    obrigacoes = await cidadania_repo.obter_obrigacoes_fiscais(session)

    total_doc = len(documentos)
    docs_validos = sum(1 for d in documentos if d.estado_validade in ["valido", "vitalicio"])
    docs_a_expirar = sum(1 for d in documentos if d.estado_validade in ["a_expirar", "urgente"])
    total_ob = len(obrigacoes)

    return templates.TemplateResponse(
        request,
        "cidadania.html",
        {
            "documentos": documentos,
            "obrigacoes": obrigacoes,
            "total_documentos": total_doc,
            "docs_validos": docs_validos,
            "docs_a_expirar": docs_a_expirar,
            "total_obrigacoes": total_ob,
        },
    )


@router.get("/api/cidadania/resumo")
async def resumo_cidadania(session: AsyncSession = Depends(get_session)):
    """Resumo para widget do AVA Hub Cockpit."""
    documentos = await cidadania_repo.obter_documentos(session)
    obrigacoes = await cidadania_repo.obter_obrigacoes_fiscais(session)

    a_expirar = [
        {"titular": d.titular_nome, "tipo": d.nome_legivel, "dias": d.dias_restantes, "validade": str(d.data_validade)}
        for d in documentos if d.estado_validade in ["a_expirar", "urgente"]
    ]
    fiscais_pendentes = [
        {"nome": o.nome, "data_limite": str(o.data_limite), "categoria": o.categoria}
        for o in obrigacoes if not o.pago
    ]

    return {
        "total_documentos": len(documentos),
        "docs_a_expirar": a_expirar,
        "docs_a_expirar_count": len(a_expirar),
        "proximas_obrigacoes_fiscais": fiscais_pendentes[:3],
    }


@router.post("/api/cidadania/documentos")
async def adicionar_documento(
    titular_nome: str = Form(...),
    tipo: str = Form(...),
    numero: str = Form(...),
    data_emissao: Optional[date] = Form(None),
    data_validade: Optional[date] = Form(None),
    entidade_emissora: Optional[str] = Form("República Portuguesa"),
    notas: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session),
):
    await cidadania_repo.criar_documento(
        session,
        titular_nome=titular_nome,
        tipo=tipo,
        numero=numero,
        data_emissao=data_emissao,
        data_validade=data_validade,
        entidade_emissora=entidade_emissora or "República Portuguesa",
        notas=notas,
    )
    return RedirectResponse(url="/", status_code=303)


@router.post("/api/cidadania/obrigacoes")
async def adicionar_obrigacao(
    nome: str = Form(...),
    categoria: str = Form("irs"),
    ano_fiscal: int = Form(2026),
    data_limite: date = Form(...),
    valor_estimado: Optional[Decimal] = Form(None),
    detalhes: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session),
):
    await cidadania_repo.criar_obrigacao_fiscal(
        session,
        nome=nome,
        categoria=categoria,
        ano_fiscal=ano_fiscal,
        data_limite=data_limite,
        valor_estimado=valor_estimado,
        detalhes=detalhes,
    )
    return RedirectResponse(url="/", status_code=303)
