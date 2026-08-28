from ava.extraction.parsers.generic_receipt import parse_generic_receipt
import uuid
from datetime import date
import logging
import unicodedata
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import ValidationError

from ava.extraction.schema_recibo import ReciboVencimentoExtraido
from ava.ingestion.pipeline._comum import (
    FalhaValidacao,
    _alertar_revisao_manual,
    _iterar_documentos_pendentes,
    _obter_item_concluido_com_documento,
)
from ava.integrations.paperless import PaperlessClient
from ava.repositories import documento_repo, fila_repo, recorrente_repo, conta_repo

logger = logging.getLogger("ava.pipeline.recibos")

TAG_RECIBO_POR_ESTRUTURAR = "recibo-por-estruturar"


def _remove_accents(input_str: str) -> str:
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    return u"".join([c for c in nfkd_form if not unicodedata.combining(c)])


async def processar_recibos_pendentes(
    session: AsyncSession, paperless: PaperlessClient, *, referencia: date
) -> None:
    async for paperless_id, texto_ocr, registado_por, ambito, tag_id in _iterar_documentos_pendentes(
        session, paperless, TAG_RECIBO_POR_ESTRUTURAR
    ):
        recibo_nivel0 = parse_generic_receipt(texto_ocr)
        
        if recibo_nivel0 is not None:
            documento = await documento_repo.criar_documento(
                session,
                paperless_document_id=paperless_id,
                nivel_extracao=0,
                dados_extraidos=recibo_nivel0.model_dump(mode="json"),
                registado_por=registado_por,
                ambito=ambito,
            )
            validado = await _processar_recibo_extraido(
                session, documento=documento, recibo=recibo_nivel0, referencia=referencia, texto_ocr=texto_ocr
            )
            if validado:
                await paperless.remover_tag(paperless_id, tag_id=tag_id)
            await session.commit()
        else:
            documento = await documento_repo.criar_documento(
                session,
                paperless_document_id=paperless_id,
                nivel_extracao=1,
                dados_extraidos={},
                registado_por=registado_por,
                ambito=ambito,
            )
            await fila_repo.criar_item(
                session, documento_id=documento.id, texto_ocr=texto_ocr, tipo="recibo_vencimento"
            )
            await session.commit()


async def _processar_recibo_extraido(
    session: AsyncSession, *, documento, recibo: ReciboVencimentoExtraido, referencia: date, texto_ocr: str = ""
) -> bool:
    titular_id = documento.registado_por
    
    if titular_id is None and texto_ocr:
        from ava.repositories.titular_repo import listar_titulares
        titulares = await listar_titulares(session)
        texto_norm = _remove_accents(texto_ocr.lower())
        for t in titulares:
            primeiro_nome = _remove_accents(t.nome.split()[0].lower())
            if primeiro_nome in texto_norm:
                titular_id = t.id
                documento.registado_por = t.id
                break

    # Apenas o cartão refeição é processado e cria um movimento de entrada na conta respetiva
    # Nota: `conta_repo.listar_contas` nunca existiu (só `listar_todas`) — segundo bug deste
    # bloco morto, descoberto ao correr o teste desta tarefa (não estava documentado no plano).
    contas = await conta_repo.listar_todas(session)
    conta_refeicao = None
    for c in contas:
        if c.titular_id == titular_id and ("Refeição" in c.nome or "Refeicao" in c.nome or "Alimentação" in c.nome):
            conta_refeicao = c
            break

    if conta_refeicao and recibo.cartao_refeicao > 0:
        from ava.repositories.movimento_repo import criar_movimento, LinhaNova
        from ava.repositories.categoria_repo import obter_por_nomes
        # Nota: este bloco NÃO escreve saldo_historico. O carregamento é um movimento; o saldo do
        # cartão é derivado dele (spec 2026-08-08, §7.2). A versão anterior gravava aqui uma
        # âncora calculada a partir do próprio movimento — um número que não podia desmentir o
        # razão — e importava uma função que nem sequer existia.
        from calendar import monthrange

        # Usar o último dia do mês para o carregamento
        try:
            _, last_day = monthrange(recibo.ano_referencia, recibo.mes_referencia)
            data_mov = date(recibo.ano_referencia, recibo.mes_referencia, last_day)
        except ValueError:
            data_mov = referencia

        # Nota: `categoria_repo.listar_todas` também nunca existiu — terceiro bug deste bloco
        # morto (o segundo foi `conta_repo.listar_contas`, ver acima). Substituído pelo mesmo
        # padrão que ava.ingestion.pipeline.faturas já usa para resolver uma categoria concreta:
        # busca direta por grupo+nome. None é aceitável — a linha fica por categorizar (A-P4).
        cat_alimentacao = await obter_por_nomes(session, grupo="Rendimentos", nome="Subsídio de alimentação")

        await criar_movimento(
            session,
            tipo="entrada",
            valor=recibo.cartao_refeicao,
            data=data_mov,
            linhas=[
                LinhaNova(
                    valor=recibo.cartao_refeicao,
                    categoria_id=cat_alimentacao.id if cat_alimentacao else None,
                    descricao="Sub. Alimentação"
                )
            ],
            origem="pipeline",
            conta_id=conta_refeicao.id,
            titular_id=titular_id,
            registado_por=titular_id,
            documento_id=documento.id,
            descricao=f"Carregamento Cartão Refeição - {recibo.mes_referencia}/{recibo.ano_referencia}"
        )

    # Opcionalmente atualizar o recorrente de alimentação
    recorrentes = await recorrente_repo.listar_ativos(session)
    for r in recorrentes:
        if r.titular_id == titular_id:
            if "Alimentação" in r.descricao or "Refeição" in r.descricao:
                r.valor = recibo.cartao_refeicao

    # Além disso, o documento_repo marca como validado
    documento.estado_validacao = "validado"
    return True


async def finalizar_recibo_vencimento(
    session: AsyncSession, *, item_id: uuid.UUID, paperless: PaperlessClient, referencia: date
) -> None:
    resultado = await _obter_item_concluido_com_documento(session, item_id)
    if resultado is None:
        return
    item, documento = resultado

    if documento.estado_validacao == "validado":
        return

    try:
        recibo = ReciboVencimentoExtraido.model_validate(item.resultado_json)
    except ValidationError:
        documento.estado_validacao = "revisao_manual"
        await _alertar_revisao_manual(session, documento)
        await session.commit()
        return

    documento.dados_extraidos = recibo.model_dump(mode="json")
    
    try:
        validado = await _processar_recibo_extraido(
            session, documento=documento, recibo=recibo, referencia=referencia, texto_ocr=item.texto_ocr or ""
        )
    except FalhaValidacao:
        documento.estado_validacao = "revisao_manual"
        await _alertar_revisao_manual(session, documento)
        await session.commit()
        return

    if validado:
        tag_id = await paperless.obter_id_de_tag(TAG_RECIBO_POR_ESTRUTURAR)
        await paperless.remover_tag(documento.paperless_document_id, tag_id=tag_id)
        
    await session.commit()
