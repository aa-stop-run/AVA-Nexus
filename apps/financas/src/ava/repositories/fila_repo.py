import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.item_fila import ItemFila


async def criar_item(
    session: AsyncSession,
    *,
    texto_ocr: str,
    documento_id: uuid.UUID | None = None,
    tipo: str = "fatura",
    contexto: dict | None = None,
) -> ItemFila:
    item = ItemFila(documento_id=documento_id, texto_ocr=texto_ocr, tipo=tipo, contexto=contexto or {})
    session.add(item)
    await session.flush()
    return item


async def obter_por_id(session: AsyncSession, item_id: uuid.UUID) -> ItemFila | None:
    return await session.get(ItemFila, item_id)


async def obter_proximo_pendente(session: AsyncSession) -> ItemFila | None:
    result = await session.execute(
        select(ItemFila)
        .where(ItemFila.estado == "pendente")
        .order_by(ItemFila.criado_em)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return result.scalar_one_or_none()


async def marcar_em_processamento(session: AsyncSession, item_id: uuid.UUID) -> None:
    item = await session.get(ItemFila, item_id)
    assert item is not None
    item.estado = "em_processamento"


async def concluir(session: AsyncSession, item_id: uuid.UUID, resultado: dict) -> None:
    item = await session.get(ItemFila, item_id)
    assert item is not None
    item.estado = "concluido"
    item.resultado_json = resultado


async def marcar_erro(session: AsyncSession, item_id: uuid.UUID, mensagem: str) -> None:
    item = await session.get(ItemFila, item_id)
    assert item is not None
    item.estado = "erro"
    item.resultado_json = {"erro": mensagem}


async def listar_pendentes_ou_em_processamento(session: AsyncSession) -> list[ItemFila]:
    result = await session.execute(
        select(ItemFila).where(ItemFila.estado.in_(["pendente", "em_processamento"]))
    )
    return list(result.scalars().all())


async def listar_com_erro(session: AsyncSession) -> list[ItemFila]:
    result = await session.execute(select(ItemFila).where(ItemFila.estado == "erro"))
    return list(result.scalars().all())
