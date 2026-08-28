import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ava.models.documento import Documento


async def criar_documento(
    session: AsyncSession,
    *,
    paperless_document_id: int,
    nivel_extracao: int,
    dados_extraidos: dict,
    estado_validacao: str = "pendente",
    registado_por: uuid.UUID | None = None,
    ambito: str = "comum",
) -> Documento:
    documento = Documento(
        paperless_document_id=paperless_document_id,
        nivel_extracao=nivel_extracao,
        dados_extraidos=dados_extraidos,
        estado_validacao=estado_validacao,
        registado_por=registado_por,
        ambito=ambito,
    )
    session.add(documento)
    await session.flush()
    return documento


async def obter_por_paperless_id(session: AsyncSession, paperless_document_id: int) -> Documento | None:
    result = await session.execute(
        select(Documento).where(Documento.paperless_document_id == paperless_document_id)
    )
    return result.scalar_one_or_none()


async def obter_por_id(session: AsyncSession, documento_id: uuid.UUID) -> Documento | None:
    return await session.get(Documento, documento_id)


async def listar_por_estado(session: AsyncSession, estado: str) -> list[Documento]:
    result = await session.execute(
        select(Documento).where(Documento.estado_validacao == estado).order_by(Documento.criado_em.desc())
    )
    return list(result.scalars().all())


async def listar_com_resumo_de_ingestao(
    session: AsyncSession, *, desde: date
) -> list[Documento]:
    """Documentos ingeridos a partir de `desde` que registaram contadores de ingestão.

    Os documentos anteriores à coluna `resumo_ingestao` têm-na a NULL e ficam de fora — a
    ausência lê-se como "ingerido antes de isto existir", não como "zero linhas".
    """
    resultado = await session.execute(
        select(Documento)
        .where(Documento.resumo_ingestao.is_not(None), Documento.criado_em >= desde)
        .order_by(Documento.criado_em.desc())
    )
    return list(resultado.scalars().all())
