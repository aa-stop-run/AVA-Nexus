from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import uuid
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.movimento import Movimento
from ava.models.movimento_linha import MovimentoLinha
from ava.models.categoria import Categoria
from ava.models.grupo_categoria import GrupoCategoria
from ava.models.contrato import Contrato


@dataclass
class SubscricaoDetetada:
    id: str
    nome: str
    categoria_nome: str
    valor_periodo: Decimal
    periodicidade: str  # "mensal", "anual", "trimestral"
    custo_anual: Decimal
    acao_simulada: str = "manter"  # "manter", "cancelar", "renegociar"
    fornecedor_nome: str | None = None
    data_ultimo_pagamento: date | None = None


@dataclass
class DesvioCategoria:
    categoria_id: uuid.UUID | None
    categoria_nome: str
    grupo_nome: str
    gasto_mes_atual: Decimal
    media_historica: Decimal
    diferenca_valor: Decimal
    diferenca_percentagem: Decimal
    tem_excesso: bool
    sugestao_poupanca_10pct: Decimal


@dataclass
class ContratoOtimizacao:
    id: uuid.UUID
    nome: str
    tipo: str
    valor_mensal: Decimal | None
    data_fim: date | None
    dias_aviso_previo: int
    em_janela_aviso: bool
    proximo_renovacao_dias: int | None


def calcular_anualizado(valor: Decimal, periodicidade: str = "mensal") -> Decimal:
    """Converte um valor periódico no seu custo anual estimado."""
    p = periodicidade.lower()
    if p in ("mensal", "month", "monthly"):
        return (valor * Decimal("12")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif p in ("trimestral", "quarterly"):
        return (valor * Decimal("4")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif p in ("semestral", "biannual"):
        return (valor * Decimal("2")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif p in ("anual", "year", "yearly"):
        return valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    elif p in ("semanal", "weekly"):
        return (valor * Decimal("52")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return (valor * Decimal("12")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calcular_desvio_mensal(
    categoria_id: uuid.UUID | None,
    categoria_nome: str,
    grupo_nome: str,
    gasto_mes_atual: Decimal,
    media_historica: Decimal,
) -> DesvioCategoria:
    """Calcula a diferença entre o gasto do mês e a média histórica."""
    diferenca_valor = gasto_mes_atual - media_historica
    if media_historica > Decimal("0"):
        diff_pct = ((diferenca_valor / media_historica) * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    else:
        diff_pct = Decimal("100.00") if gasto_mes_atual > Decimal("0") else Decimal("0.00")

    # Considera excesso se estiver mais de 10% e mais de 15€ acima da média histórica
    tem_excesso = diferenca_valor >= Decimal("15.00") and diff_pct >= Decimal("10.00")
    sugestao_poupanca = (gasto_mes_atual * Decimal("0.10")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    return DesvioCategoria(
        categoria_id=categoria_id,
        categoria_nome=categoria_nome,
        grupo_nome=grupo_nome,
        gasto_mes_atual=gasto_mes_atual,
        media_historica=media_historica,
        diferenca_valor=diferenca_valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        diferenca_percentagem=diff_pct,
        tem_excesso=tem_excesso,
        sugestao_poupanca_10pct=sugestao_poupanca,
    )


def calcular_resumo_poupanca(
    subscricoes: list[SubscricaoDetetada],
    desvios: list[DesvioCategoria],
    poupanca_extra_mensal: Decimal = Decimal("0"),
) -> dict[str, Any]:
    """Calcula o somatório do potencial de poupança mensal e anual."""
    poupanca_subscricoes_mensal = Decimal("0")
    poupanca_subscricoes_anual = Decimal("0")

    for s in subscricoes:
        if s.acao_simulada == "cancelar":
            if s.periodicidade == "anual":
                mensal_equiv = (s.valor_periodo / Decimal("12")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                poupanca_subscricoes_mensal += mensal_equiv
            else:
                poupanca_subscricoes_mensal += s.valor_periodo
            poupanca_subscricoes_anual += s.custo_anual

    # Sugestões de corte em categorias em excesso
    poupanca_desvios_mensal = sum(
        (d.sugestao_poupanca_10pct for d in desvios if d.tem_excesso), Decimal("0")
    )
    poupanca_desvios_anual = (poupanca_desvios_mensal * Decimal("12")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    total_mensal = (
        poupanca_subscricoes_mensal + poupanca_desvios_mensal + poupanca_extra_mensal
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_anual = (poupanca_subscricoes_anual + poupanca_desvios_anual + (poupanca_extra_mensal * Decimal("12"))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    return {
        "poupanca_mensal_estimada": total_mensal,
        "poupanca_anual_estimada": total_anual,
        "total_subscricoes_analisadas": len(subscricoes),
        "total_subscricoes_a_cancelar": sum(1 for s in subscricoes if s.acao_simulada == "cancelar"),
        "total_categorias_em_excesso": sum(1 for d in desvios if d.tem_excesso),
    }


async def extrair_subscricoes_recorrentes(
    session: AsyncSession,
    *,
    de: date,
    ate: date,
    titular_id: uuid.UUID | None = None,
) -> list[SubscricaoDetetada]:
    """Obtém todas as despesas periódicas identificadas pelo motor de recorrentes."""
    stmt = (
        select(Movimento, MovimentoLinha, Categoria)
        .join(MovimentoLinha, MovimentoLinha.movimento_id == Movimento.id)
        .join(Categoria, Categoria.id == MovimentoLinha.categoria_id)
        .where(
            Movimento.data >= de,
            Movimento.data <= ate,
            Movimento.tipo == "saida",
        )
        .order_by(Movimento.data.desc())
    )
    if titular_id:
        stmt = stmt.where(Movimento.titular_id == titular_id)

    result = await session.execute(stmt)
    linhas = result.all()

    # Agrupa movimentos por descrição/fornecedor
    grupos: dict[str, list[dict]] = {}
    for mov, linha, cat in linhas:
        chave = mov.descricao.strip().upper()
        if chave not in grupos:
            grupos[chave] = []
        grupos[chave].append(
            {
                "id": mov.id,
                "data": mov.data,
                "valor": linha.valor,
                "categoria_nome": cat.nome,
                "descricao": mov.descricao,
            }
        )

    subscricoes: list[SubscricaoDetetada] = []
    idx = 1
    for desc, movs in grupos.items():
        if len(movs) >= 2:  # Apareceu 2 ou mais vezes no intervalo
            valores = [m["valor"] for m in movs]
            val_medio = (sum(valores, Decimal("0")) / Decimal(len(valores))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            cat_nome = movs[0]["categoria_nome"]
            data_ult = max(m["data"] for m in movs)
            custo_anual = calcular_anualizado(val_medio, periodicidade="mensal")

            subscricoes.append(
                SubscricaoDetetada(
                    id=f"sub-{idx}",
                    nome=desc.title(),
                    categoria_nome=cat_nome,
                    valor_periodo=val_medio,
                    periodicidade="mensal",
                    custo_anual=custo_anual,
                    acao_simulada="manter",
                    data_ultimo_pagamento=data_ult,
                )
            )
            idx += 1

    # Ordena por custo anual decrescente
    subscricoes.sort(key=lambda s: s.custo_anual, reverse=True)
    return subscricoes


async def analisar_desvios_categorias_db(
    session: AsyncSession,
    *,
    ano: int,
    mes: int,
    titular_id: uuid.UUID | None = None,
) -> list[DesvioCategoria]:
    """Compara as despesas do mês indicado com a média dos 3 meses anteriores."""
    import calendar

    # Mês atual
    primeiro_dia_mes = date(ano, mes, 1)
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    fim_mes = date(ano, mes, ultimo_dia)

    # 3 meses anteriores
    mes_ant3 = mes - 3
    ano_ant3 = ano
    if mes_ant3 <= 0:
        mes_ant3 += 12
        ano_ant3 -= 1
    inicio_historico = date(ano_ant3, mes_ant3, 1)
    fim_historico = primeiro_dia_mes - timedelta(days=1)

    # Query gastos mês atual por categoria
    q_atual = (
        select(
            Categoria.id.label("cat_id"),
            Categoria.nome.label("cat_nome"),
            GrupoCategoria.nome.label("grupo_nome"),
            func.coalesce(func.sum(MovimentoLinha.valor), Decimal("0")).label("total"),
        )
        .join(MovimentoLinha, MovimentoLinha.categoria_id == Categoria.id)
        .join(GrupoCategoria, GrupoCategoria.id == Categoria.grupo_id)
        .join(Movimento, Movimento.id == MovimentoLinha.movimento_id)
        .where(
            Movimento.data >= primeiro_dia_mes,
            Movimento.data <= fim_mes,
            Movimento.tipo == "saida",
        )
        .group_by(Categoria.id, Categoria.nome, GrupoCategoria.nome)
    )
    if titular_id:
        q_atual = q_atual.where(Movimento.titular_id == titular_id)

    res_atual = await session.execute(q_atual)
    gastos_atuais = {r.cat_id: (r.cat_nome, r.grupo_nome, r.total) for r in res_atual.all()}

    # Query média dos 3 meses anteriores
    q_hist = (
        select(
            Categoria.id.label("cat_id"),
            Categoria.nome.label("cat_nome"),
            GrupoCategoria.nome.label("grupo_nome"),
            func.coalesce(func.sum(MovimentoLinha.valor), Decimal("0")).label("total_hist"),
        )
        .join(MovimentoLinha, MovimentoLinha.categoria_id == Categoria.id)
        .join(GrupoCategoria, GrupoCategoria.id == Categoria.grupo_id)
        .join(Movimento, Movimento.id == MovimentoLinha.movimento_id)
        .where(
            Movimento.data >= inicio_historico,
            Movimento.data <= fim_historico,
            Movimento.tipo == "saida",
        )
        .group_by(Categoria.id, Categoria.nome, GrupoCategoria.nome)
    )
    if titular_id:
        q_hist = q_hist.where(Movimento.titular_id == titular_id)

    res_hist = await session.execute(q_hist)
    gastos_hist = {r.cat_id: (r.cat_nome, r.grupo_nome, r.total_hist / Decimal("3")) for r in res_hist.all()}

    todos_cat_ids = set(gastos_atuais.keys()).union(gastos_hist.keys())
    desvios: list[DesvioCategoria] = []

    for cid in todos_cat_ids:
        cat_nome, grupo_nome, atual = gastos_atuais.get(cid, ("Outros", "Geral", Decimal("0")))
        if cid in gastos_hist:
            _, _, media = gastos_hist[cid]
        else:
            media = Decimal("0")

        desvio = calcular_desvio_mensal(
            categoria_id=cid,
            categoria_nome=cat_nome,
            grupo_nome=grupo_nome,
            gasto_mes_atual=atual,
            media_historica=media,
        )
        desvios.append(desvio)

    # Ordena pelos desvios positivos mais expressivos
    desvios.sort(key=lambda d: d.diferenca_valor, reverse=True)
    return desvios


async def extrair_contratos_otimizacao(
    session: AsyncSession,
    *,
    hoje: date,
) -> list[ContratoOtimizacao]:
    """Lista contratos ativos e sinaliza janelas de aviso prévio e renegociação."""
    stmt = select(Contrato).where(Contrato.ativo.is_(True)).order_by(Contrato.data_fim.asc().nulls_last())
    result = await session.execute(stmt)
    contratos = result.scalars().all()

    lista: list[ContratoOtimizacao] = []
    for c in contratos:
        dias_fim = (c.data_fim - hoje).days if c.data_fim else None
        aviso = c.dias_aviso_previo or 30
        em_aviso = dias_fim is not None and 0 <= dias_fim <= (aviso + 15)

        lista.append(
            ContratoOtimizacao(
                id=c.id,
                nome=c.nome,
                tipo=c.tipo,
                valor_mensal=c.valor,
                data_fim=c.data_fim,
                dias_aviso_previo=aviso,
                em_janela_aviso=em_aviso,
                proximo_renovacao_dias=dias_fim,
            )
        )
    return lista
