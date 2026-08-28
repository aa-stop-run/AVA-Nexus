import pytest

from ava.repositories import documento_repo, fila_repo


@pytest.mark.asyncio
async def test_ciclo_de_vida_do_item_da_fila(db_session):
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=7, nivel_extracao=1, dados_extraidos={}
    )

    item = await fila_repo.criar_item(db_session, documento_id=documento.id, texto_ocr="texto ocr")
    assert item.estado == "pendente"

    proximo = await fila_repo.obter_proximo_pendente(db_session)
    assert proximo is not None
    assert proximo.id == item.id

    await fila_repo.marcar_em_processamento(db_session, item.id)
    assert (await fila_repo.obter_proximo_pendente(db_session)) is None

    await fila_repo.concluir(db_session, item.id, {"valor_total": "45.67"})
    atualizado = await fila_repo.obter_por_id(db_session, item.id)
    assert atualizado.estado == "concluido"
    assert atualizado.resultado_json == {"valor_total": "45.67"}


@pytest.mark.asyncio
async def test_marcar_erro(db_session):
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=8, nivel_extracao=1, dados_extraidos={}
    )

    item = await fila_repo.criar_item(db_session, documento_id=documento.id, texto_ocr="texto ocr")
    assert item.estado == "pendente"

    await fila_repo.marcar_erro(db_session, item.id, "alguma mensagem de erro")
    atualizado = await fila_repo.obter_por_id(db_session, item.id)
    assert atualizado.estado == "erro"
    assert atualizado.resultado_json == {"erro": "alguma mensagem de erro"}
