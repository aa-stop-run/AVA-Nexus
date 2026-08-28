import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ava.api.shared import _contar_alertas, templates
from ava.db import get_session
from ava.financas.saldos import parse_valor_pt
from ava.models.contrato import Contrato
from ava.repositories import ativo_repo, contrato_repo, fornecedor_repo, titular_repo

router = APIRouter(tags=["contratos"])


@router.get("/contratos")
async def listar_contratos(
    request: Request,
    tipo: str | None = None,
    titular_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    tid = uuid.UUID(titular_id) if titular_id else None
    todos = await contrato_repo.listar_todos(
        session, apenas_ativos=True, tipo=tipo, titular_id=tid
    )
    titulares = await titular_repo.listar_titulares(session)
    titulares_map = {t.id: t.nome for t in titulares}
    ativos = await ativo_repo.listar_todos_ativos(session)
    ativos_map = {a.id: a.nome for a in ativos}
    fornecedores = await fornecedor_repo.listar_todos(session)
    fornecedores_map = {f.id: f.nome for f in fornecedores}

    hoje = date.today()
    seguros_contratos = []
    garantias = []

    for c in todos:
        dias_restantes = (c.data_fim - hoje).days if c.data_fim else None
        data_decisao = (
            c.data_fim - timedelta(days=c.dias_aviso_previo) if c.data_fim else None
        )
        dias_decisao = (data_decisao - hoje).days if data_decisao else None

        item = {
            "contrato": c,
            "titular_nome": titulares_map.get(c.titular_id, "Comum"),
            "ativo_nome": ativos_map.get(c.ativo_id) if c.ativo_id else None,
            "fornecedor_nome": fornecedores_map.get(c.fornecedor_id)
            if c.fornecedor_id
            else None,
            "tipo_label": contrato_repo.TIPO_LABELS.get(c.tipo, c.tipo),
            "periodicidade_label": contrato_repo.PERIODICIDADE_LABELS.get(
                c.periodicidade, c.periodicidade
            ),
            "dias_restantes": dias_restantes,
            "data_decisao": data_decisao,
            "dias_decisao": dias_decisao,
            "valor_anualizado": contrato_repo.calcular_valor_anualizado(
                c.valor, c.periodicidade
            ),
        }

        if c.tipo == "garantia":
            status_garantia = "Valida"
            if dias_restantes is not None:
                if dias_restantes < 0:
                    status_garantia = "Expirada"
                elif dias_restantes <= 60:
                    status_garantia = "A expirar"
            item["status_garantia"] = status_garantia
            garantias.append(item)
        else:
            seguros_contratos.append(item)

    encargo_anual = await contrato_repo.calcular_encargo_anual_total(session)
    vencimentos_proximos = await contrato_repo.listar_proximos_vencimentos(
        session, referencia=hoje, dias_antecedencia=60
    )

    return templates.TemplateResponse(
        request,
        "contratos.html",
        {
            "seguros_contratos": seguros_contratos,
            "garantias": garantias,
            "encargo_anual": encargo_anual,
            "total_seguros_contratos": len(seguros_contratos),
            "total_garantias": len(garantias),
            "total_vencimentos_proximos": len(vencimentos_proximos),
            "total_alertas": await _contar_alertas(session),
            "tipo_labels": contrato_repo.TIPO_LABELS,
            "filtro_tipo": tipo or "",
            "filtro_titular": titular_id or "",
            "titulares": titulares,
        },
    )


@router.get("/contratos/novo")
async def form_contrato_novo(
    request: Request,
    ativo_id: str | None = None,
    tipo: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    titulares = await titular_repo.listar_titulares(session)
    ativos = await ativo_repo.listar_todos_ativos(session)
    fornecedores = await fornecedor_repo.listar_todos(session)

    return templates.TemplateResponse(
        request,
        "contrato_novo.html",
        {
            "titulares": titulares,
            "ativos": ativos,
            "fornecedores": fornecedores,
            "selected_ativo_id": ativo_id or "",
            "selected_tipo": tipo or "seguro_auto",
            "tipo_labels": contrato_repo.TIPO_LABELS,
            "periodicidade_labels": contrato_repo.PERIODICIDADE_LABELS,
            "total_alertas": await _contar_alertas(session),
            "hoje": date.today().isoformat(),
        },
    )


@router.post("/contratos/novo")
async def criar_contrato_post(
    request: Request,
    titular_id: str = Form(...),
    nome: str = Form(...),
    tipo: str = Form(...),
    data_inicio: str = Form(...),
    data_fim: str = Form(""),
    ativo_id: str = Form(""),
    fornecedor_id: str = Form(""),
    numero_referencia: str = Form(""),
    renovacao_automatica: str = Form("false"),
    dias_aviso_previo: int = Form(30),
    valor: str = Form(""),
    periodicidade: str = Form("mensal"),
    notas: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    t_id = uuid.UUID(titular_id)
    a_id = uuid.UUID(ativo_id) if ativo_id.strip() else None
    f_id = uuid.UUID(fornecedor_id) if fornecedor_id.strip() else None
    dt_inicio = date.fromisoformat(data_inicio)
    dt_fim = date.fromisoformat(data_fim) if data_fim.strip() else None
    is_renovacao = renovacao_automatica.lower() in ("true", "1", "on", "yes")

    val_dec = None
    if valor.strip():
        try:
            val_dec = parse_valor_pt(valor)
        except InvalidOperation:
            val_dec = None

    await contrato_repo.criar_contrato(
        session,
        titular_id=t_id,
        ativo_id=a_id,
        fornecedor_id=f_id,
        nome=nome,
        tipo=tipo,
        numero_referencia=numero_referencia,
        data_inicio=dt_inicio,
        data_fim=dt_fim,
        renovacao_automatica=is_renovacao,
        dias_aviso_previo=dias_aviso_previo,
        valor=val_dec,
        periodicidade=periodicidade,
        notas=notas,
    )
    await session.commit()

    if a_id:
        return RedirectResponse(
            url=f"/patrimonio/ativos/{a_id}?msg=Contrato registado com sucesso",
            status_code=303,
        )
    return RedirectResponse(
        url="/contratos?msg=Contrato registado com sucesso", status_code=303
    )


@router.post("/contratos/{contrato_id}/desativar")
async def desativar_contrato_post(
    contrato_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    await contrato_repo.desativar_contrato(session, contrato_id)
    return RedirectResponse(
        url="/contratos?msg=Contrato cancelado/arquivado", status_code=303
    )
