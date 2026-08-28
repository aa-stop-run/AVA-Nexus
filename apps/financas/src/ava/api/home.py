import calendar
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.api.shared import _contar_alertas, _despesas_por_grupo, templates
from ava.db import get_session
from ava.models.movimento import Movimento
from ava.models.movimento_linha import MovimentoLinha
from ava.financas.metas import calcular_progresso_meta
from ava.repositories import (
    conta_repo,
    contrato_repo,
    fila_repo,
    fornecedor_repo,
    insights_repo,
    margem_repo,
    meta_poupanca_repo,
    movimento_repo,
    obrigacao_repo,
    orcamento_repo,
    saldo_historico_repo,
)

router = APIRouter(tags=["home"])


@router.get("/")
async def home(
    request: Request,
    periodo: str | None = None,
    titular_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    hoje = date.today()
    ano, mes = hoje.year, hoje.month
    if periodo:
        try:
            ano_pedido, mes_pedido = (int(parte) for parte in periodo.split("-"))
            date(ano_pedido, mes_pedido, 1)  # valida o mês (1-12) e o ano
        except (ValueError, TypeError):
            pass  # "periodo" malformado (ex.: mês fora de 1-12) — mantém o mês atual
        else:
            ano, mes = ano_pedido, mes_pedido
    inicio_mes = date(ano, mes, 1)
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    fim_mes = date(ano, mes, ultimo_dia)

    ano_anterior, mes_anterior = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    ano_seguinte, mes_seguinte = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    esta_no_mes_atual = (ano, mes) == (hoje.year, hoje.month)

    try:
        tid = uuid.UUID(titular_id) if titular_id else None
    except ValueError:
        tid = None

    serie_patrimonio = await saldo_historico_repo.listar_patrimonio_liquido_no_tempo(session)
    # [-1][2] = total (financeiro + bens, com bens projetados quando não há avaliação na data
    # exata); [-1][1] é só o financeiro — saldos reais, sem estimativa nenhuma. O KPI mais visível
    # da app mostra o total (patrimonio_atual), por isso o template rotula-o "Património Total" e
    # marca-o com uma nota de que inclui bens estimados: não é um facto puro como o financeiro.
    if serie_patrimonio:
        patrimonio_financeiro_atual = serie_patrimonio[-1][1]
        patrimonio_atual = serie_patrimonio[-1][2]
    else:
        patrimonio_financeiro_atual = Decimal("0")
        patrimonio_atual = Decimal("0")
    total_bens_atual = patrimonio_atual - patrimonio_financeiro_atual

    despesas = await movimento_repo.totais_por_categoria(
        session, inicio=inicio_mes, fim=fim_mes, tipo=("saida", "transferencia"), titular_id=tid
    )
    rendimentos = await movimento_repo.totais_por_categoria(
        session, inicio=inicio_mes, fim=fim_mes, tipo="entrada", titular_id=tid
    )

    total_despesas = sum((total for _, _, total in despesas), Decimal("0"))
    total_rendimentos = sum((total for _, _, total in rendimentos), Decimal("0"))
    encargos_financeiros = sum(
        (
            total
            for grupo, _, total in despesas
            if grupo.nome == "Encargos financeiros"
        ),
        Decimal("0"),
    )
    despesas_por_grupo = _despesas_por_grupo(despesas, total_despesas)

    orcamentos = await orcamento_repo.listar_orcamentos(session, ano, mes)
    orcamento_map = {o.grupo_categoria_id: o for o in orcamentos}
    for item in despesas_por_grupo:
        gid = item["grupo"].id
        o = orcamento_map.get(gid)
        if o:
            item["limite_mensal"] = o.limite_mensal
            item["percent_orcamento"] = (
                float(item["total"] / o.limite_mensal * 100) if o.limite_mensal > 0 else 0
            )
        else:
            item["limite_mensal"] = None
            item["percent_orcamento"] = None

    margem = await margem_repo.margem_estrutural(
        session, de=inicio_mes, ate=fim_mes, titular_id=tid
    )

    # Rendimentos por fonte, com a natureza (ordinária/extraordinária) de cada categoria — a
    # mesma distinção que já alimenta a margem estrutural (spec 2026-08-13 §2), agora visível
    # junto de cada linha em vez de escondida numa secção à parte na barra lateral (achado de
    # 2026-08-20: essa secção ficava desalinhada a meio da página na versão web).
    rendimentos_com_natureza = [
        {
            "grupo": grupo.nome,
            "categoria": categoria.nome,
            "total": total,
            "extraordinaria": categoria.natureza == "extraordinario",
        }
        for grupo, categoria, total in rendimentos
    ]

    # As entradas SEM categoria contam para `margem.rendimento_extraordinario` (default seguro,
    # spec §3.3) mas não aparecem em `rendimentos` (a query exige categoria) — sem esta linha, a
    # tabela nunca somava o total mostrado pela margem e quem tentasse conferir encontrava uma
    # diferença sem explicação.
    resto = margem.rendimento_extraordinario - sum(
        (r["total"] for r in rendimentos_com_natureza if r["extraordinaria"]), Decimal("0")
    )
    if resto:
        rendimentos_com_natureza.append({
            "grupo": "Sem categoria",
            "categoria": "Sem categoria",
            "total": resto,
            "extraordinaria": True,
        })

    # Total de transferências GERAIS (inclui cartões de crédito) que não têm categoria
    result_transf = await session.execute(
        select(func.sum(Movimento.valor))
        .join(MovimentoLinha, Movimento.id == MovimentoLinha.movimento_id)
        .where(
            Movimento.tipo == "transferencia",
            MovimentoLinha.categoria_id.is_(None),
            Movimento.data >= inicio_mes,
            Movimento.data <= fim_mes,
        )
    )
    total_transferencias = result_transf.scalar() or Decimal("0")
    total_saidas = total_despesas + total_transferencias

    obrigacoes = await obrigacao_repo.listar_pendentes(session)
    proximas = [
        {"obrigacao": o, "dias_restantes": (o.data_limite - hoje).days}
        for o in obrigacoes[:5]
    ]
    falhas = await fila_repo.listar_com_erro(session)

    contas = await conta_repo.listar_todas_ativas(session)
    liquidez_atual = Decimal("0")
    saldo_conta_principal = None
    nome_conta_principal = None

    contas_alvo = [c for c in contas if c.titular_id == tid] if tid else contas
    for conta in contas_alvo:
        if conta.tipo in ("a_ordem", "poupanca"):
            derivado_mes = await saldo_historico_repo.saldo_derivado(session, conta, ate=fim_mes)
            if derivado_mes:
                liquidez_atual += derivado_mes.valor
                if conta.tipo == "a_ordem":
                    if (
                        saldo_conta_principal is None
                        or "bpi" in conta.instituicao.lower()
                        or "bpi" in conta.nome.lower()
                    ):
                        saldo_conta_principal = derivado_mes.valor
                        nome_conta_principal = conta.nome

    if saldo_conta_principal is None:
        saldo_conta_principal = liquidez_atual

    cartoes_refeicao = [c for c in contas if c.tipo == "cartao_refeicao"]

    todos_insights = await insights_repo.listar_insights(
        session,
        ano=ano,
        mes=mes,
        titular_id=tid,
        margem_atual=margem.margem,
        despesas_atuais=despesas,
        poupanca_atual=margem.poupanca,
    )
    insights_resumo = todos_insights[:3]

    metas_todas = await meta_poupanca_repo.listar_metas(session, apenas_ativas=True)
    metas_progressos = [calcular_progresso_meta(m, hoje=hoje) for m in metas_todas]

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "periodo": f"{ano:04d}-{mes:02d}",
            "periodo_anterior": f"{ano_anterior:04d}-{mes_anterior:02d}",
            "periodo_seguinte": f"{ano_seguinte:04d}-{mes_seguinte:02d}",
            "esta_no_mes_atual": esta_no_mes_atual,
            "patrimonio_atual": patrimonio_atual,
            "total_bens_atual": total_bens_atual,
            "despesas_por_grupo": despesas_por_grupo,
            "total_despesas": total_despesas,
            "total_transferencias": total_transferencias,
            "total_saidas": total_saidas,
            "total_rendimentos": total_rendimentos,
            "margem": margem,
            "rendimentos_com_natureza": rendimentos_com_natureza,
            "encargos_financeiros": encargos_financeiros,
            "liquidez_atual": liquidez_atual,
            "saldo_conta_principal": saldo_conta_principal,
            "nome_conta_principal": nome_conta_principal,
            "proximas_obrigacoes": proximas,
            "total_falhas": len(falhas),
            "total_alertas": await _contar_alertas(session),
            "insights_resumo": insights_resumo,
            "total_insights": len(todos_insights),
            "cartoes_refeicao": cartoes_refeicao,
            "metas_progressos": metas_progressos,
        },
    )


@router.get("/insights")
async def insights_view(
    request: Request,
    periodo: str | None = None,
    titular_id: str | None = None,
    fornecedor_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    hoje = date.today()
    ano, mes = hoje.year, hoje.month
    if periodo:
        try:
            ano_pedido, mes_pedido = (int(parte) for parte in periodo.split("-"))
            date(ano_pedido, mes_pedido, 1)
        except (ValueError, TypeError):
            pass
        else:
            ano, mes = ano_pedido, mes_pedido
    ano_anterior, mes_anterior = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    ano_seguinte, mes_seguinte = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    esta_no_mes_atual = (ano, mes) == (hoje.year, hoje.month)
    try:
        tid = uuid.UUID(titular_id) if titular_id else None
    except ValueError:
        tid = None

    todos_insights = await insights_repo.listar_insights(session, ano=ano, mes=mes, titular_id=tid)

    ROTULOS_AREA = {
        "patrimonio": "Património",
        "margem": "Margem",
        "despesas": "Despesas",
        "saude": "Saúde",
    }
    ORDEM_AREAS = ["patrimonio", "margem", "despesas", "saude"]
    por_area: dict[str, list] = {}
    for insight in todos_insights:
        por_area.setdefault(insight.area, []).append(insight)
    grupos = [
        {"area": area, "rotulo": ROTULOS_AREA.get(area, area.title()), "insights": itens}
        for area, itens in por_area.items()
    ]
    grupos.sort(key=lambda g: ORDEM_AREAS.index(g["area"]) if g["area"] in ORDEM_AREAS else 99)

    # "Explorar por fornecedor" (spec §5): consulta à parte, fora da lista de insights -- não
    # tem gatilho, é o utilizador que escolhe o que quer ver.
    fornecedores = await fornecedor_repo.listar_com_despesas(session)
    try:
        fid = uuid.UUID(fornecedor_id) if fornecedor_id else None
    except ValueError:
        fid = None
    historico_fornecedor = (
        await movimento_repo.historico_pagamentos_fornecedor(session, fid) if fid else None
    )

    return templates.TemplateResponse(
        request,
        "insights.html",
        {
            "grupos": grupos,
            "periodo": f"{ano:04d}-{mes:02d}",
            "periodo_anterior": f"{ano_anterior:04d}-{mes_anterior:02d}",
            "periodo_seguinte": f"{ano_seguinte:04d}-{mes_seguinte:02d}",
            "esta_no_mes_atual": esta_no_mes_atual,
            "total_alertas": await _contar_alertas(session),
            "fornecedores": fornecedores,
            "fornecedor_selecionado_id": fornecedor_id if fid else "",
            "historico_fornecedor": historico_fornecedor,
        },
    )


@router.get("/prazos")
async def prazos(request: Request, session: AsyncSession = Depends(get_session)):
    obrigacoes = await obrigacao_repo.listar_pendentes(session)
    hoje = date.today()
    linhas_obrigacoes = [
        {"obrigacao": o, "dias_restantes": (o.data_limite - hoje).days} for o in obrigacoes
    ]
    vencimentos_contratos = await contrato_repo.listar_proximos_vencimentos(
        session, referencia=hoje, dias_antecedencia=90
    )

    return templates.TemplateResponse(
        request,
        "prazos.html",
        {
            "obrigacoes": linhas_obrigacoes,
            "vencimentos_contratos": vencimentos_contratos,
            "total_alertas": await _contar_alertas(session),
            "tipo_labels": contrato_repo.TIPO_LABELS,
        },
    )
