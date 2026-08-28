import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.ativo_valor import AtivoValor


async def registar_valor(
    session: AsyncSession,
    *,
    ativo_id: uuid.UUID,
    data: date,
    valor: Decimal,
    origem: str = "observado",
) -> AtivoValor:
    """Grava uma avaliação observada. Já existindo uma na mesma data, substitui-a.

    Ao contrário de saldo_historico_repo.registar_saldo (que levanta SaldoDuplicado), aqui a
    repetição é o caso normal: o utilizador corrige um valor que acabou de meter mal. Um erro
    obrigá-lo-ia a apagar antes de regravar, sem nada ganhar.
    """
    existente = await session.execute(
        select(AtivoValor).where(AtivoValor.ativo_id == ativo_id, AtivoValor.data == data)
    )
    avaliacao = existente.scalar_one_or_none()
    if avaliacao is not None:
        avaliacao.valor = valor
        avaliacao.origem = origem
        await session.flush()
        return avaliacao

    avaliacao = AtivoValor(ativo_id=ativo_id, data=data, valor=valor, origem=origem)
    session.add(avaliacao)
    await session.flush()
    return avaliacao


async def obter_valor_em_data(
    session: AsyncSession, ativo_id: uuid.UUID, data_limite: date
) -> AtivoValor | None:
    """A observação mais recente até `data_limite`, inclusive. None se não houver nenhuma —
    um bem não tem valor conhecido antes de alguém o ter avaliado (nunca se extrapola para trás).
    """
    result = await session.execute(
        select(AtivoValor)
        .where(AtivoValor.ativo_id == ativo_id, AtivoValor.data <= data_limite)
        .order_by(AtivoValor.data.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def obter_por_id(session: AsyncSession, avaliacao_id: uuid.UUID) -> AtivoValor | None:
    return await session.get(AtivoValor, avaliacao_id)


async def listar_por_ativo(session: AsyncSession, ativo_id: uuid.UUID) -> list[AtivoValor]:
    """Da mais recente para a mais antiga — é a ordem em que a página de detalhe as mostra."""
    result = await session.execute(
        select(AtivoValor).where(AtivoValor.ativo_id == ativo_id).order_by(AtivoValor.data.desc())
    )
    return list(result.scalars().all())


async def apagar(session: AsyncSession, avaliacao_id: uuid.UUID) -> bool:
    avaliacao = await session.get(AtivoValor, avaliacao_id)
    if avaliacao is None:
        return False
    await session.delete(avaliacao)
    await session.flush()
    return True
