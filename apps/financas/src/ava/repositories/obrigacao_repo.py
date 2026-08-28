import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.obrigacao import Obrigacao


async def criar_obrigacao(
    session: AsyncSession,
    *,
    tipo: str,
    descricao: str,
    data_limite: date,
    origem: str,
    titular_id: uuid.UUID | None = None,
    documento_id: uuid.UUID | None = None,
    ativo_id: uuid.UUID | None = None,
) -> Obrigacao:
    obrigacao = Obrigacao(
        tipo=tipo,
        descricao=descricao,
        data_limite=data_limite,
        origem=origem,
        titular_id=titular_id,
        documento_id=documento_id,
        ativo_id=ativo_id,
    )
    session.add(obrigacao)
    await session.flush()
    return obrigacao


async def listar_pendentes(session: AsyncSession) -> list[Obrigacao]:
    result = await session.execute(
        select(Obrigacao).where(Obrigacao.estado == "pendente").order_by(Obrigacao.data_limite)
    )
    return list(result.scalars().all())


async def existe_obrigacao(
    session: AsyncSession,
    *,
    tipo: str,
    data_limite: date,
    titular_id: uuid.UUID | None,
    ativo_id: uuid.UUID | None = None,
) -> bool:
    # ativo_id faz parte da chave de dedupe: dois ativos do mesmo titular registados na mesma
    # data de matricula produzem a MESMA data_limite computada (proxima_inspecao/proxima_iuc) —
    # sem ativo_id aqui, a obrigação do segundo ativo seria descartada como "duplicada" da do
    # primeiro, silenciosamente (ver sincronizar_obrigacoes_ativo).
    result = await session.execute(
        select(Obrigacao.id).where(
            Obrigacao.tipo == tipo,
            Obrigacao.data_limite == data_limite,
            Obrigacao.titular_id == titular_id,
            Obrigacao.ativo_id == ativo_id,
        )
    )
    return result.scalar_one_or_none() is not None
