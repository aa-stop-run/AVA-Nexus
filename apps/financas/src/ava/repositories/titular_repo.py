import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.titular import Titular


async def criar_titular(
    session: AsyncSession,
    *,
    nome: str,
    tipo: str,
    data_nascimento: date | None = None,
) -> Titular:
    titular = Titular(
        nome=nome, tipo=tipo, data_nascimento=data_nascimento
    )
    session.add(titular)
    await session.flush()
    return titular


async def obter_titular(session: AsyncSession, titular_id: uuid.UUID) -> Titular | None:
    return await session.get(Titular, titular_id)


async def listar_titulares(session: AsyncSession) -> list[Titular]:
    result = await session.execute(select(Titular).order_by(Titular.nome))
    return list(result.scalars().all())


