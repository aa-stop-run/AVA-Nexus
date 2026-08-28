import uuid
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ava.financas.saldos import TIPOS_PASSIVO, derivar
from ava.models.ativo import Ativo
from ava.models.conta import Conta
from ava.models.saldo_historico import SaldoHistorico
from ava.repositories import ativo_repo, ativo_valor_repo, conta_repo, movimento_repo


class SaldoDuplicado(Exception):
    pass


async def registar_saldo(
    session: AsyncSession,
    *,
    conta_id: uuid.UUID,
    data: date,
    valor: Decimal,
    origem: str = "extrato",
) -> SaldoHistorico:
    """Grava uma âncora. `origem` diz quem a declarou — ver SaldoHistorico.origem.

    A omissão é "extrato" porque esse é o caminho de longe mais comum e porque as 57 âncoras
    que já existiam quando a coluna foi criada vieram todas de extratos.
    """
    saldo = SaldoHistorico(conta_id=conta_id, data=data, valor=valor, origem=origem)
    try:
        async with session.begin_nested():
            session.add(saldo)
            await session.flush()
    except IntegrityError as exc:
        raise SaldoDuplicado(f"já existe saldo para a conta {conta_id} na data {data}") from exc
    return saldo


async def obter_saldo_mais_recente(session: AsyncSession, conta_id: uuid.UUID) -> SaldoHistorico | None:
    result = await session.execute(
        select(SaldoHistorico)
        .where(SaldoHistorico.conta_id == conta_id)
        .order_by(SaldoHistorico.data.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def obter_saldo_mais_recente_por_origem(
    session: AsyncSession, conta_id: uuid.UUID, *, origem: str
) -> SaldoHistorico | None:
    """A âncora mais recente desta conta que uma origem ESPECÍFICA declarou.

    Diferente de `obter_saldo_mais_recente`: essa devolve a última palavra de QUALQUER fonte;
    esta devolve a última vez que UMA fonte em concreto falou. Usada quando o que importa não é
    "o que se sabe por último", mas "até onde esta fonte já provou cobertura" — ex.: um ficheiro
    do BPI Net não prova cobertura de período nenhuma (o próprio rodapé avisa que só traz o que
    estava no ecrã), por isso `importacao_ficheiro.importar` usa a de origem="extrato" para saber
    até onde o extrato já cobriu, e `divergencia_repo.listar_por_confirmar_antigos` usa a mesma
    para saber desde quando o banco falou por último (revisão final da spec 2026-08-09, achados
    3 e 6).
    """
    result = await session.execute(
        select(SaldoHistorico)
        .where(SaldoHistorico.conta_id == conta_id, SaldoHistorico.origem == origem)
        .order_by(SaldoHistorico.data.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def obter_saldo_exato(session: AsyncSession, conta_id: uuid.UUID, data: date) -> SaldoHistorico | None:
    """A âncora exatamente nesta data, se existir. `obter_saldo_em_data` devolve a mais recente
    até à data, que é outra pergunta."""
    result = await session.execute(
        select(SaldoHistorico).where(
            SaldoHistorico.conta_id == conta_id, SaldoHistorico.data == data
        )
    )
    return result.scalar_one_or_none()


async def obter_saldo_em_data(session: AsyncSession, conta_id: uuid.UUID, data_limite: date) -> SaldoHistorico | None:
    result = await session.execute(
        select(SaldoHistorico)
        .where(SaldoHistorico.conta_id == conta_id, SaldoHistorico.data <= data_limite)
        .order_by(SaldoHistorico.data.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


class SaldoDerivado(NamedTuple):
    """O saldo estimado de uma conta, com a proveniência que o UI precisa de mostrar."""

    valor: Decimal
    ancora_valor: Decimal
    ancora_data: date
    ancora_origem: str
    e_estimado: bool


async def saldo_derivado(
    session: AsyncSession, conta: Conta, *, ate: date | None = None
) -> SaldoDerivado | None:
    """Saldo de uma conta numa data: âncora mais recente + movimentos desde ela.

    Devolve `None` quando a conta não tem âncora nenhuma. Não devolve zero de propósito: uma
    soma de movimentos sem ponto de partida não é um saldo, e mostrar `0,00 €` numa conta de
    dívida afirmaria que não se deve nada (spec §3.2).

    `e_estimado` distingue "isto é o que o banco disse" de "isto é o que o banco disse mais o
    que registaste depois" — o UI marca o segundo como estimativa, tal como `ativo_valor` já faz
    com `e_projetado`.
    """
    data_alvo = ate or date.today()
    ancora = await obter_saldo_em_data(session, conta.id, data_alvo)
    if ancora is None:
        return None

    entradas, saidas = await movimento_repo.fluxo_entre(
        session, conta.id, de=ancora.data, ate=data_alvo
    )
    valor = derivar(ancora.valor, entradas, saidas, tipo=conta.tipo)
    return SaldoDerivado(
        valor=valor,
        ancora_valor=ancora.valor,
        ancora_data=ancora.data,
        ancora_origem=ancora.origem,
        e_estimado=(entradas != 0 or saidas != 0),
    )


async def listar_evolucao(session: AsyncSession, conta_id: uuid.UUID) -> list[SaldoHistorico]:
    result = await session.execute(
        select(SaldoHistorico).where(SaldoHistorico.conta_id == conta_id).order_by(SaldoHistorico.data)
    )
    return list(result.scalars().all())


async def _valor_bens_em(session: AsyncSession, ativos: list[Ativo], data_ref: date) -> Decimal:
    """Soma o valor de todos os bens nessa data (ativo_repo.valor_em_data) — um bem sem
    observação até essa data não contribui (ver a docstring de listar_patrimonio_liquido_no_tempo).
    Partilhada entre o ramo histórico e o ponto de hoje, que fazem exatamente a mesma soma para
    datas diferentes."""
    total = Decimal("0")
    for ativo in ativos:
        avaliacao = await ativo_repo.valor_em_data(session, ativo, data_ref)
        if avaliacao is not None:
            total += avaliacao.valor
    return total


async def listar_patrimonio_liquido_no_tempo(
    session: AsyncSession,
) -> list[tuple[date, Decimal, Decimal, bool]]:
    """(data, patrimonio_financeiro, patrimonio_total, e_estimado) em cada data com um saldo ou
    avaliação, mais um ponto final de hoje.

    Financeiro = contas não-dívida menos dívidas, usando o saldo mais recente conhecido de cada
    conta até essa data ("last known value", sem interpolação).

    Total = financeiro mais o valor dos bens ATIVOS nessa data (ativo_repo.valor_em_data). Um bem
    sem observação até essa data não contribui — a versão anterior somava-lhe o valor de HOJE em
    todas as datas desde a aquisição, o que projetava o presente para trás e mostrava um carro
    que sempre valeu o que vale agora.

    Implementado em Python, não numa consulta janelada: o volume (dezenas de contas, um saldo por
    extrato mensal) torna isto trivialmente rápido e muito mais fácil de ler e testar.
    """
    contas = await conta_repo.listar_todas_ativas(session)
    ativos = await ativo_repo.listar_todos_ativos(session)

    saldos_por_conta: dict[uuid.UUID, list[SaldoHistorico]] = {}
    datas: set[date] = set()
    for conta in contas:
        saldos = await listar_evolucao(session, conta.id)
        if saldos:
            saldos_por_conta[conta.id] = saldos
            datas.update(s.data for s in saldos)

    for ativo in ativos:
        for avaliacao in await ativo_valor_repo.listar_por_ativo(session, ativo.id):
            datas.add(avaliacao.data)

    if not datas:
        return []

    resultado: list[tuple[date, Decimal, Decimal, bool]] = []
    for data_ref in sorted(datas):
        financeiro = Decimal("0")
        for conta in contas:
            mais_recente: SaldoHistorico | None = None
            for saldo in saldos_por_conta.get(conta.id, []):
                if saldo.data <= data_ref:
                    mais_recente = saldo
                else:
                    break
            if mais_recente is not None:
                if conta.tipo in TIPOS_PASSIVO:
                    financeiro -= mais_recente.valor
                else:
                    financeiro += mais_recente.valor

        total = financeiro + await _valor_bens_em(session, ativos, data_ref)

        resultado.append((data_ref, financeiro, total, False))

    # Um ponto final "hoje, estimado": os pontos históricos são âncoras confirmadas, este é
    # âncora + movimentos desde ela. Marcado como estimativa para o gráfico o poder desenhar
    # diferente — a mesma convenção que `ativo_valor.e_projetado` já usa nos bens.
    #
    # SEMPRE se acrescenta, substituindo (não preservando) um eventual ponto histórico de hoje.
    # Uma âncora de hoje numa conta, ou uma avaliação de bem datada de hoje (ambas entram em
    # `datas`, acima), só cobre ESSA conta ou ESSE bem — as restantes contas continuam a precisar
    # dos movimentos derivados desde a SUA própria âncora. Preservar o ponto histórico nesse caso
    # escondia esses movimentos: bastava uma âncora ou uma avaliação de hoje, de uma só conta ou
    # bem entre várias, para o KPI de património da home e o último ponto do gráfico deixarem de
    # contar tudo o resto — silenciosamente, e sem que /patrimonio (que não tem este atalho)
    # concordasse (revisão final da spec 2026-08-08, achado 4).
    hoje = date.today()
    financeiro_hoje = Decimal("0")
    # Verdadeiro se ALGUMA conta contribuiu com um saldo estimado (âncora + movimentos depois
    # dela). Antes ficava fixo em True — quando hoje tem âncora confirmada e nenhum movimento
    # desde ela, o valor é idêntico ao confirmado, e o gráfico desenhava tracejado (a marca de
    # "isto é estimativa") um número que não é estimativa nenhuma (achado 3 da re-revisão).
    algum_estimado = False
    for conta in contas:
        derivado = await saldo_derivado(session, conta, ate=hoje)
        if derivado is not None:
            if conta.tipo in TIPOS_PASSIVO:
                financeiro_hoje -= derivado.valor
            else:
                financeiro_hoje += derivado.valor
            algum_estimado = algum_estimado or derivado.e_estimado

    total_hoje = financeiro_hoje + await _valor_bens_em(session, ativos, hoje)

    resultado = [ponto for ponto in resultado if ponto[0] != hoje]
    resultado.append((hoje, financeiro_hoje, total_hoje, algum_estimado))

    return resultado
