"""Helpers genuinamente partilhados pelos fluxos de fatura, extrato e recibo.

Isto existe para que uma correção como a de A2/A-P6 (idempotência, alerta ativo em
revisão manual) só precise de ser feita aqui, uma vez, em vez de replicada em cada
módulo de domínio (faturas.py / extratos.py / recibos.py / aprovacao.py).
"""

import uuid
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from ava.integrations.paperless import PaperlessClient
from ava.models.documento import Documento
from ava.models.item_fila import ItemFila
from ava.repositories import alerta_repo, documento_repo, fila_repo


class FalhaValidacao(Exception):
    pass


def _extrair_atribuicao_por_tags(
    tag_ids: list[int], mapa_tags: dict[int, str]
) -> tuple[uuid.UUID | None, str]:
    """Lê titular e âmbito das tags do Paperless de um documento."""
    titular_id: uuid.UUID | None = None
    ambito = "comum"
    for tag_id in tag_ids:
        nome = mapa_tags.get(tag_id, "")
        if nome.startswith("titular-"):
            titular_id = uuid.UUID(nome.removeprefix("titular-"))
        elif nome.startswith("telegram-titular-"):
            titular_id = uuid.UUID(nome.removeprefix("telegram-titular-"))
        elif nome == "ambito-pessoal":
            ambito = "pessoal"
    return titular_id, ambito


async def _alertar_revisao_manual(session: AsyncSession, documento: Documento) -> None:
    # A-P6 (falha nunca é silenciosa): um documento a cair em revisão manual não pode ser um
    # estado meramente passivo (só visível se alguém abrir /revisao por acaso) — gera-se um
    # alerta ativo. Chave de deduplicação assente no documento: retries do mesmo documento
    # (ex.: uma segunda chamada a finalizar_*_nivel1 antes de o item mudar de estado) não
    # duplicam o alerta, graças à unique constraint de alerta_repo.criar_se_novo.
    await alerta_repo.criar_se_novo(
        session,
        tipo="documento_revisao_manual",
        chave_deduplicacao=f"documento_revisao_manual:{documento.id}",
        mensagem=f"Documento {documento.id} precisa de revisão manual — consulte /revisao no dashboard.",
    )


async def _iterar_documentos_pendentes(
    session: AsyncSession, paperless: PaperlessClient, tag_nome: str
) -> AsyncIterator[tuple[int, str, uuid.UUID | None, str, int]]:
    """Skeleton de polling comum a `processar_documentos_pendentes` (faturas) e
    `processar_extratos_pendentes` (extratos): localiza o id do tag, lista os documentos
    marcados com esse tag, salta os já criados numa corrida anterior (idempotência — A2),
    obtém o texto OCR e resolve a atribuição por tags (titular/âmbito).

    Cede, por documento ainda por processar, o tuplo
    `(paperless_id, texto_ocr, registado_por, ambito, tag_id)` — o `tag_id` vai incluído
    porque ambos os chamadores precisam dele mais tarde para `paperless.remover_tag`.

    O que acontece a seguir (parser nível-0 usado, se `ambito` é sequer relevante, o que
    fazer quando falta o titular, e se há um passo de reconciliação no final) diverge o
    suficiente entre faturas e extratos para não valer a pena forçar esse resto para aqui
    também — ver a nota em `faturas.processar_documentos_pendentes` /
    `extratos.processar_extratos_pendentes`.
    """
    tag_id = await paperless.obter_id_de_tag(tag_nome)
    mapa_tags = await paperless.obter_mapa_de_tags()
    documentos = await paperless.listar_documentos_por_tag(tag_nome)

    for doc in documentos:
        paperless_id = doc["id"]
        if await documento_repo.obter_por_paperless_id(session, paperless_id) is not None:
            continue  # já criado numa corrida anterior — idempotência (A2)

        texto_ocr = await paperless.obter_conteudo(paperless_id)
        registado_por, ambito = _extrair_atribuicao_por_tags(doc.get("tags", []), mapa_tags)

        yield paperless_id, texto_ocr, registado_por, ambito, tag_id


async def _obter_item_concluido_com_documento(
    session: AsyncSession, item_id: uuid.UUID
) -> tuple[ItemFila, Documento] | None:
    """Cabeçalho comum a `finalizar_documento_nivel1` e `finalizar_extrato_nivel1`: só avança
    quando o item da fila está exatamente "concluido" com resultado (idempotência — A2, um
    item já "finalizado" ou ainda pendente/em processamento não deve reprocessar), e o
    documento a que aponta ainda existe (um item órfão é sinalizado via fila_repo.marcar_erro
    em vez de falhar silenciosamente — A-P6).

    Devolve `None` quando o chamador deve parar de imediato (já tratado aqui, incluindo o
    commit do marcar_erro no caso de órfão); caso contrário devolve `(item, documento)`.
    """
    item = await fila_repo.obter_por_id(session, item_id)
    if item is None or item.estado != "concluido" or item.resultado_json is None:
        return None

    documento = await documento_repo.obter_por_id(session, item.documento_id)
    if documento is None:
        # órfão: o item da fila aponta para um documento que já não existe — nunca deveria
        # acontecer em condições normais, mas não pode ficar sem sinal (A-P6).
        await fila_repo.marcar_erro(
            session,
            item_id,
            f"documento {item.documento_id} referenciado pelo item da fila não foi encontrado",
        )
        await session.commit()
        return None

    return item, documento
