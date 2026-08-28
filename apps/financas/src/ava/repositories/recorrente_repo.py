import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.recorrente import Recorrente


async def criar_recorrente(
    session: AsyncSession,
    *,
    tipo: str,
    categoria_id: uuid.UUID,
    titular_id: uuid.UUID,
    valor: Decimal,
    dia_do_mes: int,
    conta_id: uuid.UUID | None = None,
    descricao: str = "",
) -> Recorrente:
    recorrente = Recorrente(
        tipo=tipo,
        categoria_id=categoria_id,
        conta_id=conta_id,
        titular_id=titular_id,
        valor=valor,
        dia_do_mes=dia_do_mes,
        descricao=descricao,
    )
    session.add(recorrente)
    await session.flush()
    return recorrente


async def listar_ativos(session: AsyncSession) -> list[Recorrente]:
    # ORDER BY determinístico (Achado 3, revisão final Fase A): sem isto a ordem de iteração em
    # gerar_movimentos_recorrentes_do_mes era arbitrária, o que tornava o cenário "saudável antes
    # do inválido" não reprodutível de forma fiável em teste. Não é o próprio commit-por-item que
    # depende disto, mas torna o comportamento previsível e testável.
    result = await session.execute(
        select(Recorrente).where(Recorrente.ativo.is_(True)).order_by(Recorrente.dia_do_mes, Recorrente.id)
    )
    return list(result.scalars().all())
