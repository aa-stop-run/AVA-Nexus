import uuid

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.fornecedor import Fornecedor
from ava.models.movimento import Movimento


async def listar_todos(session: AsyncSession) -> list[Fornecedor]:
    result = await session.execute(select(Fornecedor).order_by(Fornecedor.nome))
    return list(result.scalars().all())


async def listar_com_despesas(session: AsyncSession) -> list[Fornecedor]:
    """Fornecedores com pelo menos uma despesa registada, por nome -- para o seletor de "Explorar
    por fornecedor" em /insights (spec 2026-08-20-insights-financeiros-design §5). Um fornecedor
    sem despesa nenhuma não tem histórico para mostrar; não faz sentido oferecê-lo na lista.
    """
    tem_despesa = exists().where(
        Movimento.fornecedor_id == Fornecedor.id, Movimento.tipo == "saida"
    )
    result = await session.execute(
        select(Fornecedor).where(tem_despesa).order_by(Fornecedor.nome)
    )
    return list(result.scalars().all())


async def obter_ou_criar(session: AsyncSession, *, nome: str, tipo: str, nif: str | None = None) -> Fornecedor:
    result = await session.execute(select(Fornecedor).where(Fornecedor.nome == nome))
    fornecedor = result.scalar_one_or_none()
    if fornecedor is not None:
        return fornecedor

    fornecedor = Fornecedor(nome=nome, tipo=tipo, nif=nif)
    session.add(fornecedor)
    await session.flush()
    return fornecedor


async def marcar_parser_nivel0(session: AsyncSession, fornecedor_id: uuid.UUID) -> None:
    fornecedor = await session.get(Fornecedor, fornecedor_id)
    assert fornecedor is not None
    fornecedor.tem_parser_nivel0 = True
