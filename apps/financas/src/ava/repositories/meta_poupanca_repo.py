import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.meta_poupanca import MetaPoupanca


async def criar_meta(
    session: AsyncSession,
    *,
    nome: str,
    valor_alvo: Decimal,
    valor_atual: Decimal = Decimal("0.00"),
    data_alvo: date | None = None,
    conta_id: uuid.UUID | None = None,
    descricao: str | None = None,
    ordem: int = 0,
) -> MetaPoupanca:
    meta = MetaPoupanca(
        nome=nome,
        valor_alvo=valor_alvo,
        valor_atual=valor_atual,
        data_alvo=data_alvo,
        conta_id=conta_id,
        descricao=descricao,
        ordem=ordem,
        ativo=True,
    )
    session.add(meta)
    await session.flush()
    return meta


async def obter_por_id(session: AsyncSession, meta_id: uuid.UUID) -> MetaPoupanca | None:
    res = await session.execute(select(MetaPoupanca).where(MetaPoupanca.id == meta_id))
    return res.scalar_one_or_none()


async def listar_metas(
    session: AsyncSession, *, apenas_ativas: bool = True
) -> list[MetaPoupanca]:
    stmt = select(MetaPoupanca)
    if apenas_ativas:
        stmt = stmt.where(MetaPoupanca.ativo.is_(True))
    stmt = stmt.order_by(MetaPoupanca.ordem, MetaPoupanca.nome)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def ajustar_valor_atual(
    session: AsyncSession,
    *,
    meta_id: uuid.UUID,
    delta: Decimal | None = None,
    novo_valor: Decimal | None = None,
) -> MetaPoupanca | None:
    meta = await obter_por_id(session, meta_id)
    if meta is None:
        return None
    if novo_valor is not None:
        meta.valor_atual = max(Decimal("0.00"), novo_valor)
    elif delta is not None:
        meta.valor_atual = max(Decimal("0.00"), meta.valor_atual + delta)
    await session.flush()
    return meta


async def atualizar_meta(
    session: AsyncSession,
    *,
    meta_id: uuid.UUID,
    nome: str,
    valor_alvo: Decimal,
    data_alvo: date | None = None,
    conta_id: uuid.UUID | None = None,
    descricao: str | None = None,
) -> MetaPoupanca | None:
    meta = await obter_por_id(session, meta_id)
    if meta is None:
        return None
    meta.nome = nome
    meta.valor_alvo = valor_alvo
    meta.data_alvo = data_alvo
    meta.conta_id = conta_id
    meta.descricao = descricao
    await session.flush()
    return meta


async def remover_meta(session: AsyncSession, meta_id: uuid.UUID) -> bool:
    meta = await obter_por_id(session, meta_id)
    if meta is None:
        return False
    await session.delete(meta)
    await session.flush()
    return True
