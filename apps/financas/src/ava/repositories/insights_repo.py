"""Orquestração de I/O para os insights financeiros: lê os dados de cada repo, entrega-os já
formados às funções puras de `ava.financas.insights`, junta e ordena o resultado.

Não escreve nada — leitura agregada calculada a cada pedido, como `margem_repo`.
"""

import calendar
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.financas.insights import (
    Insight,
    calcular_mensalidade,
    calcular_projecao_poupanca,
    calcular_racio_custos_fixos,
    calcular_recuperacao_ressarcimento,
    calcular_runway_emergencia,
    calcular_sazonalidade_utilities,
    calcular_tendencia_categoria,
    calcular_tendencia_margem,
)
from ava.financas.recorrentes import data_do_mes
from ava.models.categoria import Categoria
from ava.models.grupo_categoria import GrupoCategoria
from ava.models.movimento import Movimento
from ava.models.recorrente import Recorrente
from ava.repositories import (
    conta_repo,
    margem_repo,
    movimento_repo,
    recorrente_repo,
    ressarcimento_repo,
    saldo_historico_repo,
)

_ORDEM_TOM = {"atencao": 0, "positivo": 1, "neutro": 2}

_GRUPOS_ESSENCIAIS = {
    "Habitação",
    "Alimentação",
    "Saúde",
    "Transportes",
    "Educação",
    "Impostos e seguros",
    "Encargos financeiros",
}

_CATEGORIAS_UTILITIES = {
    "Eletricidade",
    "Água",
    "Gás",
    "Condomínio",
    "Internet e TV",
    "Telecomunicações",
}

# Janela de dias à volta do dia_do_mes configurado onde se procura o movimento real -- mesma
# lógica de janela usada em importacao_ficheiro._compativel e casamento.casar_linha, mas aqui
# nunca exige valor exato (é a diferença de valor que se quer detetar).
_JANELA_DIAS = 3

_BANDA_PLAUSIBILIDADE = Decimal("0.5")  # candidato tem de estar entre 50% e 150% do valor esperado -- fora disto e mais provavel ser um movimento nao relacionado do que o mesmo recorrente com o preco mudado


def _intervalo_do_mes(ano: int, mes: int) -> tuple[date, date]:
    inicio = date(ano, mes, 1)
    _, ultimo_dia = calendar.monthrange(ano, mes)
    return inicio, date(ano, mes, ultimo_dia)


def _mes_anterior(ano: int, mes: int) -> tuple[int, int]:
    return (ano - 1, 12) if mes == 1 else (ano, mes - 1)


async def _valor_real_do_recorrente(
    session: AsyncSession, recorrente: Recorrente, *, ano: int, mes: int, excluir_ids: set[uuid.UUID]
) -> tuple[Decimal, uuid.UUID] | None:
    """O valor e o id de um movimento real (`origem != "regra"`) que corresponda a este
    recorrente neste mês, se houver.

    Fase 1: só recorrentes com `conta_id` -- sem conta associada não há forma fiável de saber
    qual movimento é o dele (spec §6.1). Desempate determinístico (data mais próxima, depois id),
    igual ao de `casamento.casar_linha`.

    Duas proteções contra falsos positivos (achado da revisão final de 2026-08-20): a janela de
    ±3 dias por si só apanhava qualquer saída próxima na mesma conta, sem verificar se o valor
    fazia sequer sentido -- uma compra de supermercado perto da data podia ser lida como "a
    mensalidade subiu para 87€". `_BANDA_PLAUSIBILIDADE` exige que o candidato esteja entre 50%
    e 150% do valor esperado. E a janela agora fica sempre dentro do próprio mês (ano, mes) --
    sem isto, um recorrente no dia 1 ou no dia 31 podia apanhar o mês anterior/seguinte.
    `excluir_ids` (preenchido por `listar_insights`) impede que dois recorrentes faturados no
    mesmo dia reclamem o mesmo movimento.
    """
    if recorrente.conta_id is None:
        return None
    data_alvo = data_do_mes(date(ano, mes, 1), recorrente.dia_do_mes)
    inicio_mes, fim_mes = _intervalo_do_mes(ano, mes)
    inicio = max(data_alvo - timedelta(days=_JANELA_DIAS), inicio_mes)
    fim = min(data_alvo + timedelta(days=_JANELA_DIAS), fim_mes)
    valor_min = recorrente.valor * (Decimal("1") - _BANDA_PLAUSIBILIDADE)
    valor_max = recorrente.valor * (Decimal("1") + _BANDA_PLAUSIBILIDADE)
    condicoes = [
        Movimento.conta_id == recorrente.conta_id,
        Movimento.tipo == recorrente.tipo,
        Movimento.origem != "regra",
        Movimento.data >= inicio,
        Movimento.data <= fim,
        Movimento.valor >= valor_min,
        Movimento.valor <= valor_max,
    ]
    if excluir_ids:
        condicoes.append(Movimento.id.notin_(excluir_ids))
    resultado = await session.execute(
        select(Movimento).where(*condicoes).order_by(Movimento.data, Movimento.id)
    )
    candidatos = list(resultado.scalars().all())
    if not candidatos:
        return None
    candidatos.sort(key=lambda m: (abs((m.data - data_alvo).days), m.data, m.id))
    escolhido = candidatos[0]
    return escolhido.valor, escolhido.id


async def _margens_dos_ultimos_6_meses(
    session: AsyncSession, *, ano: int, mes: int, titular_id: uuid.UUID | None,
    margem_atual: Decimal | None = None,
) -> list[Decimal]:
    """Os 6 meses até (ano, mes) inclusive, mais antigo primeiro.

    `margem_atual`: quando o chamador já calculou a margem do próprio (ano, mes) por outra razão
    (ex. `dashboard.py::home()`, que já mostra a margem estrutural do mês no resto da página),
    passa-a aqui em vez de a deixar ser recalculada -- é a consulta mais pesada da página (junção
    a 4 tabelas), e sem isto era feita duas vezes na mesma visita (achado da revisão final de
    2026-08-20). `None` mantém o comportamento antigo: calcula os 6 meses, incluindo o atual.
    """
    meses: list[tuple[int, int]] = []
    a, m = ano, mes
    for _ in range(6):
        meses.append((a, m))
        a, m = _mes_anterior(a, m)
    meses.reverse()

    meses_a_calcular = meses[:-1] if margem_atual is not None else meses
    margens = []
    for a, m in meses_a_calcular:
        inicio, fim = _intervalo_do_mes(a, m)
        resumo = await margem_repo.margem_estrutural(session, de=inicio, ate=fim, titular_id=titular_id)
        margens.append(resumo.margem)
    if margem_atual is not None:
        margens.append(margem_atual)
    return margens


async def _poupancas_dos_ultimos_6_meses(
    session: AsyncSession, *, ano: int, mes: int, titular_id: uuid.UUID | None,
    poupanca_atual: Decimal | None = None,
) -> list[Decimal]:
    """Os 6 meses até (ano, mes) inclusive, mais antigo primeiro -- mesma forma de
    `_margens_dos_ultimos_6_meses`, mas para `margem.poupanca` (spec §6.5).

    Corre a sua própria série de `margem_estrutural` em vez de partilhar a de
    `_margens_dos_ultimos_6_meses` (que só guarda `.margem`) -- duplica a consulta mais pesada
    da página uma segunda vez. Aceite deliberadamente: a projeção de poupança é a fase menos
    validada do sistema de insights (spec §6.5, "a única cuja utilidade depende de ver como as
    outras se comportam primeiro"); refazer `_margens_dos_ultimos_6_meses` para devolver os dois
    campos arrisca uma função já estável e testada por um ganho que só interessa se esta fase se
    mantiver em uso real.
    """
    meses: list[tuple[int, int]] = []
    a, m = ano, mes
    for _ in range(6):
        meses.append((a, m))
        a, m = _mes_anterior(a, m)
    meses.reverse()

    meses_a_calcular = meses[:-1] if poupanca_atual is not None else meses
    poupancas = []
    for a, m in meses_a_calcular:
        inicio, fim = _intervalo_do_mes(a, m)
        resumo = await margem_repo.margem_estrutural(session, de=inicio, ate=fim, titular_id=titular_id)
        poupancas.append(resumo.poupanca)
    if poupanca_atual is not None:
        poupancas.append(poupanca_atual)
    return poupancas


async def _obter_liquidez_total(session: AsyncSession, *, ate: date) -> Decimal:
    """Soma o saldo derivado até à data de todas as contas ativas de tipo 'a_ordem' e 'poupanca'."""
    contas = await conta_repo.listar_todas_ativas(session)
    liquidez = Decimal("0")
    for conta in contas:
        if conta.tipo in ("a_ordem", "poupanca"):
            derivado = await saldo_historico_repo.saldo_derivado(session, conta, ate=ate)
            if derivado:
                liquidez += derivado.valor
    return liquidez


def _agregar_por_grupo(
    totais: list[tuple[GrupoCategoria, Categoria, Decimal]]
) -> dict[str, Decimal]:
    por_grupo: dict[str, Decimal] = {}
    for grupo, _categoria, total in totais:
        por_grupo[grupo.nome] = por_grupo.get(grupo.nome, Decimal("0")) + total
    return por_grupo


async def _consultar_totais_6_meses(
    session: AsyncSession,
    *,
    ano: int,
    mes: int,
    titular_id: uuid.UUID | None,
    despesas_atuais: list[tuple[GrupoCategoria, Categoria, Decimal]] | None = None,
) -> list[list[tuple[GrupoCategoria, Categoria, Decimal]]]:
    """Retorna os totais por categoria de cada um dos últimos 6 meses (mais antigo primeiro)."""
    meses: list[tuple[int, int]] = []
    a, m = ano, mes
    for _ in range(6):
        meses.append((a, m))
        a, m = _mes_anterior(a, m)
    meses.reverse()

    meses_a_consultar = meses[:-1] if despesas_atuais is not None else meses
    totais_por_mes: list[list[tuple[GrupoCategoria, Categoria, Decimal]]] = []
    for a, m in meses_a_consultar:
        inicio, fim = _intervalo_do_mes(a, m)
        totais = await movimento_repo.totais_por_categoria(
            session, inicio=inicio, fim=fim, tipo=("saida", "transferencia"), titular_id=titular_id
        )
        totais_por_mes.append(totais)
    if despesas_atuais is not None:
        totais_por_mes.append(despesas_atuais)
    return totais_por_mes


async def _totais_por_grupo_ultimos_6_meses(
    session: AsyncSession, *, ano: int, mes: int, titular_id: uuid.UUID | None,
    despesas_atuais: list[tuple[GrupoCategoria, Categoria, Decimal]] | None = None,
) -> list[tuple[str, list[Decimal]]]:
    """Os totais de despesa por grupo, nos últimos 6 meses (mais antigo primeiro), terminando em
    (ano, mes). Um grupo sem despesa nalgum desses meses entra com 0€ nesse mês -- a série tem
    sempre 6 posições.
    """
    totais_por_mes_raw = await _consultar_totais_6_meses(
        session, ano=ano, mes=mes, titular_id=titular_id, despesas_atuais=despesas_atuais
    )
    totais_por_mes = [_agregar_por_grupo(totais) for totais in totais_por_mes_raw]

    nomes_grupo: list[str] = []
    for mapa in totais_por_mes:
        for nome in mapa:
            if nome not in nomes_grupo:
                nomes_grupo.append(nome)

    return [
        (nome, [mapa.get(nome, Decimal("0")) for mapa in totais_por_mes])
        for nome in nomes_grupo
    ]


async def _dados_sazonalidade_utilities(
    session: AsyncSession,
    *,
    ano: int,
    mes: int,
    titular_id: uuid.UUID | None,
    totais_6_meses_raw: list[list[tuple[GrupoCategoria, Categoria, Decimal]]],
) -> list[tuple[str, Decimal, Decimal | None, Decimal]]:
    """Extrai os dados para calcular_sazonalidade_utilities: (nome, valor_atual, valor_homologo, media_recente)."""
    if not totais_6_meses_raw:
        return []
    mes_atual_raw = totais_6_meses_raw[-1]
    mapa_atual: dict[str, Decimal] = {}
    for _g, cat, total in mes_atual_raw:
        if cat.nome in _CATEGORIAS_UTILITIES or getattr(cat, "unidade_contador", None):
            mapa_atual[cat.nome] = mapa_atual.get(cat.nome, Decimal("0")) + total

    if not mapa_atual:
        return []

    # 3 meses anteriores (M-3, M-2, M-1)
    meses_recentes = totais_6_meses_raw[-4:-1] if len(totais_6_meses_raw) >= 4 else totais_6_meses_raw[:-1]
    mapas_recentes = [
        {c.nome: t for _g, c, t in mes}
        for mes in meses_recentes
    ]

    # Mês homólogo (ano - 1, mes)
    inicio_homologo, fim_homologo = _intervalo_do_mes(ano - 1, mes)
    totais_homologo_raw = await movimento_repo.totais_por_categoria(
        session, inicio=inicio_homologo, fim=fim_homologo, tipo=("saida", "transferencia"), titular_id=titular_id
    )
    if not totais_homologo_raw:
        mapa_homologo = None
    else:
        mapa_homologo = {}
        for _g, c, t in totais_homologo_raw:
            mapa_homologo[c.nome] = mapa_homologo.get(c.nome, Decimal("0")) + t

    dados: list[tuple[str, Decimal, Decimal | None, Decimal]] = []
    for cat_nome, valor_atual in mapa_atual.items():
        media_recente = (
            sum((m.get(cat_nome, Decimal("0")) for m in mapas_recentes), Decimal("0")) / Decimal(len(mapas_recentes))
            if mapas_recentes else Decimal("0")
        )
        valor_homologo = mapa_homologo.get(cat_nome, Decimal("0")) if mapa_homologo is not None else None
        dados.append((cat_nome, valor_atual, valor_homologo, media_recente))

    return dados


async def _resumos_ressarcimento_recentes(session: AsyncSession) -> list[tuple[Decimal, Decimal]]:
    """(despesas, reembolsos) de cada grupo de ressarcimento dos últimos 90 dias."""
    grupos = await ressarcimento_repo.listar_recentes(session)
    return [(resumo.despesas, resumo.reembolsos) for _grupo, resumo in grupos]


async def listar_insights(
    session: AsyncSession, *, ano: int, mes: int, titular_id: uuid.UUID | None = None,
    margem_atual: Decimal | None = None,
    despesas_atuais: list[tuple[GrupoCategoria, Categoria, Decimal]] | None = None,
    poupanca_atual: Decimal | None = None,
) -> list[Insight]:
    """Todos os insights ativos para o período, ordenados por tom (atenção primeiro)."""
    recorrentes = [
        r for r in await recorrente_repo.listar_ativos(session)
        if r.tipo == "saida" and (titular_id is None or r.titular_id == titular_id)
    ]
    pares: list[tuple[Recorrente, Decimal | None]] = []
    movimentos_reclamados: set[uuid.UUID] = set()
    for r in recorrentes:
        encontrado = await _valor_real_do_recorrente(
            session, r, ano=ano, mes=mes, excluir_ids=movimentos_reclamados
        )
        if encontrado is None:
            pares.append((r, None))
        else:
            valor_real, movimento_id = encontrado
            movimentos_reclamados.add(movimento_id)
            pares.append((r, valor_real))
    insights = calcular_mensalidade(pares)

    margens = await _margens_dos_ultimos_6_meses(
        session, ano=ano, mes=mes, titular_id=titular_id, margem_atual=margem_atual
    )
    insights += calcular_tendencia_margem(margens)

    totais_6_meses_raw = await _consultar_totais_6_meses(
        session, ano=ano, mes=mes, titular_id=titular_id, despesas_atuais=despesas_atuais
    )

    totais_por_mes = [_agregar_por_grupo(totais) for totais in totais_6_meses_raw]
    nomes_grupo: list[str] = []
    for mapa in totais_por_mes:
        for nome in mapa:
            if nome not in nomes_grupo:
                nomes_grupo.append(nome)

    totais_categoria = [
        (nome, [mapa.get(nome, Decimal("0")) for mapa in totais_por_mes])
        for nome in nomes_grupo
    ]
    insights += calcular_tendencia_categoria(totais_categoria)

    # 1. Sazonalidade de Utilities
    dados_utilities = await _dados_sazonalidade_utilities(
        session, ano=ano, mes=mes, titular_id=titular_id, totais_6_meses_raw=totais_6_meses_raw
    )
    insights += calcular_sazonalidade_utilities(dados_utilities)

    # 2. Fundo de Emergência & Runway
    _, fim_mes = _intervalo_do_mes(ano, mes)
    liquidez_total = await _obter_liquidez_total(session, ate=fim_mes)
    totais_globais = [sum((t for _, _, t in mes_totais), Decimal("0")) for mes_totais in totais_6_meses_raw]
    totais_essenciais = [
        sum((t for g, c, t in mes_totais if g.nome in _GRUPOS_ESSENCIAIS or getattr(c, "natureza", None) == "fixa"), Decimal("0"))
        for mes_totais in totais_6_meses_raw
    ]
    despesa_media_global = sum(totais_globais) / Decimal(len(totais_globais)) if totais_globais else Decimal("0")
    despesa_essencial_mensal = sum(totais_essenciais) / Decimal(len(totais_essenciais)) if totais_essenciais else Decimal("0")
    insights += calcular_runway_emergencia(
        liquidez_total=liquidez_total,
        despesa_media_global=despesa_media_global,
        despesa_essencial_mensal=despesa_essencial_mensal,
    )

    # 3. Rácio de Custos Fixos
    inicio_mes, _ = _intervalo_do_mes(ano, mes)
    resumo_margem_atual = await margem_repo.margem_estrutural(session, de=inicio_mes, ate=fim_mes, titular_id=titular_id)
    custos_fixos = resumo_margem_atual.despesa_fixa + resumo_margem_atual.servico_divida
    rendimento_ordinario = resumo_margem_atual.rendimento_recorrente
    insights += calcular_racio_custos_fixos(
        custos_fixos=custos_fixos,
        rendimento_ordinario=rendimento_ordinario,
    )

    resumos_ressarcimento = await _resumos_ressarcimento_recentes(session)
    insights += calcular_recuperacao_ressarcimento(resumos_ressarcimento)

    poupancas = await _poupancas_dos_ultimos_6_meses(
        session, ano=ano, mes=mes, titular_id=titular_id, poupanca_atual=poupanca_atual
    )
    insights += calcular_projecao_poupanca(poupancas)

    insights.sort(key=lambda i: _ORDEM_TOM.get(i.tom, 3))
    return insights

