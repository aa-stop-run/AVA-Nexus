import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.alerta import Alerta


async def criar_se_novo(
    session: AsyncSession, *, tipo: str, chave_deduplicacao: str, mensagem: str
) -> Alerta | None:
    alerta = Alerta(tipo=tipo, chave_deduplicacao=chave_deduplicacao, mensagem=mensagem)
    try:
        async with session.begin_nested():
            session.add(alerta)
            await session.flush()
    except IntegrityError:
        return None
    return alerta


async def listar_nao_enviados(session: AsyncSession) -> list[Alerta]:
    result = await session.execute(select(Alerta).where(Alerta.enviado.is_(False)))
    return list(result.scalars().all())


async def marcar_enviado(session: AsyncSession, alerta_id: uuid.UUID) -> None:
    alerta = await session.get(Alerta, alerta_id)
    assert alerta is not None
    alerta.enviado = True
    alerta.enviado_em = datetime.now(UTC)
