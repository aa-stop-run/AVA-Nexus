import calendar
import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ava.api.shared import _contar_alertas, templates
from ava.db import get_session
from ava.financas.otimizador import (
    SubscricaoDetetada,
    analisar_desvios_categorias_db,
    calcular_resumo_poupanca,
    extrair_contratos_otimizacao,
    extrair_subscricoes_recorrentes,
)
from ava.models.movimento import Movimento
from ava.models.movimento_linha import MovimentoLinha
from ava.models.categoria import Categoria
from ava.models.grupo_categoria import GrupoCategoria

router = APIRouter(prefix="/otimizador", tags=["otimizador"])


@router.get("")
async def otimizador_page(
    request: Request,
    periodo: str | None = None,
    titular_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    hoje = date.today()
    if periodo:
        try:
            partes = periodo.split("-")
            ano, mes = int(partes[0]), int(partes[1])
        except (ValueError, IndexError):
            ano, mes = hoje.year, hoje.month
    else:
        ano, mes = hoje.year, hoje.month

    ultimo_dia = calendar.monthrange(ano, mes)[1]
    fim_mes = date(ano, mes, ultimo_dia)
    inicio_6m = date(ano if mes > 6 else ano - 1, mes - 6 if mes > 6 else mes + 6, 1)

    try:
        tid = uuid.UUID(titular_id) if titular_id else None
    except ValueError:
        tid = None

    # 1. Subscrições recorrentes
    subscricoes = await extrair_subscricoes_recorrentes(
        session, de=inicio_6m, ate=fim_mes, titular_id=tid
    )

    # 2. Desvios de consumo
    desvios = await analisar_desvios_categorias_db(
        session, ano=ano, mes=mes, titular_id=tid
    )
    categorias_em_excesso = [d for d in desvios if d.tem_excesso]

    # 3. Contratos e Encargos
    contratos = await extrair_contratos_otimizacao(session, hoje=hoje)

    # Encargos financeiros (juros e comissões) do mês
    q_encargos = (
        select(func.coalesce(func.sum(MovimentoLinha.valor), Decimal("0")))
        .join(Categoria, Categoria.id == MovimentoLinha.categoria_id)
        .join(GrupoCategoria, GrupoCategoria.id == Categoria.grupo_id)
        .join(Movimento, Movimento.id == MovimentoLinha.movimento_id)
        .where(
            Movimento.data >= date(ano, mes, 1),
            Movimento.data <= fim_mes,
            Movimento.tipo == "saida",
            GrupoCategoria.nome.ilike("%encargo%"),
        )
    )
    if tid:
        q_encargos = q_encargos.where(Movimento.titular_id == tid)
    res_enc = await session.execute(q_encargos)
    total_encargos_juros = res_enc.scalar() or Decimal("0")

    # 4. Consolidação do Resumo de Poupança
    resumo = calcular_resumo_poupanca(subscricoes, desvios)

    return templates.TemplateResponse(
        request,
        "otimizador.html",
        {
            "periodo": f"{ano:04d}-{mes:02d}",
            "subscricoes": subscricoes,
            "desvios": desvios,
            "categorias_em_excesso": categorias_em_excesso,
            "contratos": contratos,
            "total_encargos_juros": total_encargos_juros,
            "resumo": resumo,
            "total_alertas": await _contar_alertas(session),
        },
    )


@router.post("/simular-acao-subscricao")
async def simular_acao_subscricao(
    request: Request,
    subscricao_id: str = Form(...),
    nome: str = Form(...),
    categoria_nome: str = Form(...),
    valor_periodo: str = Form(...),
    periodicidade: str = Form("mensal"),
    custo_anual: str = Form(...),
    nova_acao: str = Form("manter"),
):
    sub = SubscricaoDetetada(
        id=subscricao_id,
        nome=nome,
        categoria_nome=categoria_nome,
        valor_periodo=Decimal(valor_periodo),
        periodicidade=periodicidade,
        custo_anual=Decimal(custo_anual),
        acao_simulada=nova_acao,
    )
    return templates.TemplateResponse(
        request,
        "_otimizador_subscricao_card.html",
        {
            "sub": sub,
        },
    )
