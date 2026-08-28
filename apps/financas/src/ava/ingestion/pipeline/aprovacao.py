"""Aprovação manual de documentos em revisão manual (dashboard /revisao).

Módulo próprio (em vez de viver em faturas.py ou extratos.py) porque
`aprovar_documento_manualmente` faz o dispatch entre os dois fluxos — um documento em
revisão manual pode ser tanto uma fatura como um extrato bancário (mesmo `dados_extraidos`
JSON, schemas diferentes) — e assim nem faturas.py nem extratos.py precisam de se importar
mutuamente.
"""

import uuid

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ava.extraction.schema import FaturaExtraida
from ava.ingestion.pipeline.extratos import _aprovar_extrato_manualmente
from ava.ingestion.pipeline.faturas import TAG_POR_ESTRUTURAR, _inferir_tipo_fornecedor, _persistir_fatura
from ava.integrations.paperless import PaperlessClient
from ava.repositories import documento_repo, fornecedor_repo
from ava.repositories.movimento_repo import ValorNaoPositivo


async def aprovar_documento_manualmente(
    session: AsyncSession, *, documento_id: uuid.UUID, paperless: PaperlessClient
) -> bool:
    documento = await documento_repo.obter_por_id(session, documento_id)
    if documento is None or documento.estado_validacao != "revisao_manual":
        return False

    try:
        fatura = FaturaExtraida.model_validate(documento.dados_extraidos)
    except ValidationError:
        # Fix 6: pode ser um extrato bancário em revisão manual (mesmo dados_extraidos JSON,
        # schemas diferentes) — só um dos dois schemas vai validar com sucesso.
        return await _aprovar_extrato_manualmente(session, documento=documento, paperless=paperless)

    fornecedor = await fornecedor_repo.obter_ou_criar(
        session, nome=fatura.fornecedor_nome, tipo=_inferir_tipo_fornecedor(fatura)
    )
    await fornecedor_repo.marcar_parser_nivel0(session, fornecedor.id)

    try:
        await _persistir_fatura(
            session,
            documento=documento,
            fatura=fatura,
            fornecedor_id=fornecedor.id,
            tipo_fornecedor=fornecedor.tipo,
        )
    except ValorNaoPositivo:
        # Achado 3 (revisão final de fecho da Fase A): validar_fatura já rejeita valor_total <= 0
        # no caminho automático, mas a aprovação manual passa propositadamente ao lado desse crivo
        # — é o mecanismo de override do utilizador para faturas que ficaram em revisao_manual por
        # outros motivos (NIF, IBAN, data, magnitude). criar_movimento fica como última linha de
        # defesa só para este caso: um valor <= 0 nunca deveria ser aprovável, nem manualmente, e
        # sem este catch a exceção subiria sem tratamento até à rota /revisao/{id}/aprovar -> 500.
        # O raise acontece antes de documento.estado_validacao ser escrito (ver _persistir_fatura),
        # por isso o documento fica tal como estava, em revisao_manual; o rollback desfaz apenas o
        # fornecedor/flag pendentes desta chamada, nunca commitados.
        await session.rollback()
        return False
    await session.commit()

    tag_id = await paperless.obter_id_de_tag(TAG_POR_ESTRUTURAR)
    await paperless.remover_tag(documento.paperless_document_id, tag_id=tag_id)
    return True
