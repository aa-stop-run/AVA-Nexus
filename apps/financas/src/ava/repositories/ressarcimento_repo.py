"""O grupo que liga um reembolso à despesa que ele ressarce — ver ava.models.ressarcimento.

Nada aqui filtra por data: n_despesas e os totais são propriedades do GRUPO inteiro, calculadas
sempre a pedido (spec 2026-08-14, §3.3). A ambiguidade de "para qual despesa vai o reembolso"
não desaparece só porque se está a olhar para um período específico.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.movimento import Movimento
from ava.models.movimento_linha import MovimentoLinha
from ava.models.ressarcimento import Ressarcimento

_ZERO = Decimal("0")


class ResumoRessarcimento(NamedTuple):
    despesas: Decimal
    reembolsos: Decimal
    liquido: Decimal
    n_despesas: int


async def criar(session: AsyncSession) -> Ressarcimento:
    grupo = Ressarcimento()
    session.add(grupo)
    await session.flush()
    return grupo


async def resumo(session: AsyncSession, ressarcimento_id: uuid.UUID) -> ResumoRessarcimento:
    stmt = (
        select(Movimento.tipo, MovimentoLinha.valor)
        .join(MovimentoLinha, MovimentoLinha.movimento_id == Movimento.id)
        .where(MovimentoLinha.ressarcimento_id == ressarcimento_id)
    )
    despesas = _ZERO
    reembolsos = _ZERO
    n_despesas = 0
    for tipo, valor in await session.execute(stmt):
        if tipo == "saida":
            despesas += valor
            n_despesas += 1
        elif tipo == "entrada":
            reembolsos += valor
    return ResumoRessarcimento(
        despesas=despesas, reembolsos=reembolsos, liquido=despesas - reembolsos,
        n_despesas=n_despesas,
    )


async def listar_recentes(
    session: AsyncSession, *, dias: int = 90
) -> list[tuple[Ressarcimento, ResumoRessarcimento]]:
    """Grupos criados nos últimos `dias` com PELO MENOS uma linha ligada, mais recente primeiro,
    cada um com o seu resumo.

    Alimenta o seletor da célula (`_ressarcimento_cell.html`) — o utilizador escolhe a que grupo
    já existente juntar uma nova linha, vendo o resumo de cada um antes de decidir.

    Grupos vazios (sem linhas ligadas) são excluídos — não aparecem no seletor durante 90 dias
    e depois desaparecem automaticamente após esse período (conforme spec §6).
    """
    limite = date.today() - timedelta(days=dias)
    # Filtra grupos que têm pelo menos uma MovimentoLinha ligada
    has_linhas = exists().where(
        MovimentoLinha.ressarcimento_id == Ressarcimento.id
    )
    stmt = (
        select(Ressarcimento)
        .where(Ressarcimento.criado_em >= limite)
        .where(has_linhas)
        .order_by(Ressarcimento.criado_em.desc())
    )
    grupos = list((await session.execute(stmt)).scalars().all())
    return [(grupo, await resumo(session, grupo.id)) for grupo in grupos]
