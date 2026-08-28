from datetime import UTC, date, datetime, timedelta

import pytest

from ava.alerts.scheduler import (
    sincronizar_obrigacoes_dos_ativos_ativos,
    verificar_falhas_de_ingestao,
    verificar_idade_da_fila,
)
from ava.obrigacoes.regras import sincronizar_obrigacoes_ativo as sincronizar_obrigacoes_ativo_real
from ava.repositories import alerta_repo, documento_repo, fila_repo, obrigacao_repo, titular_repo, ativo_repo


@pytest.mark.asyncio
async def test_verificar_idade_da_fila_cria_alerta_para_item_antigo_e_nao_duplica(db_session):
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=1, nivel_extracao=1, dados_extraidos={}
    )
    item = await fila_repo.criar_item(db_session, documento_id=documento.id, texto_ocr="texto")
    item.criado_em = datetime.now(UTC) - timedelta(days=5)
    await db_session.commit()

    novas_chaves = await verificar_idade_da_fila(db_session)
    assert novas_chaves == [f"idade_fila:{item.id}"]

    novas_chaves_repetidas = await verificar_idade_da_fila(db_session)
    assert novas_chaves_repetidas == []


@pytest.mark.asyncio
async def test_verificar_idade_da_fila_ignora_item_recente(db_session):
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=2, nivel_extracao=1, dados_extraidos={}
    )
    await fila_repo.criar_item(db_session, documento_id=documento.id, texto_ocr="texto")
    await db_session.commit()

    assert await verificar_idade_da_fila(db_session) == []


@pytest.mark.asyncio
async def test_verificar_falhas_de_ingestao_cria_alerta(db_session):
    documento = await documento_repo.criar_documento(
        db_session, paperless_document_id=3, nivel_extracao=1, dados_extraidos={}
    )
    item = await fila_repo.criar_item(db_session, documento_id=documento.id, texto_ocr="texto")
    await fila_repo.marcar_erro(db_session, item.id, "timeout do modelo")
    await db_session.commit()

    assert await verificar_falhas_de_ingestao(db_session) == [f"falha_ingestao:{item.id}"]




@pytest.mark.asyncio
async def test_job_obrigacoes_cria_obrigacoes_para_veiculo_ativo_e_ignora_inativo(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="proprio")
    await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Corsa", data_aquisicao=date(2022, 3, 10)
    )
    await ativo_repo.criar_ativo(
        db_session,
        titular_id=titular.id,
        tipo="carro", nome="Vendido",
        data_aquisicao=date(2015, 1, 1),
        ativo_status=False,
    )
    await db_session.commit()

    await sincronizar_obrigacoes_dos_ativos_ativos(db_session, referencia=date(2026, 1, 1))

    pendentes = await obrigacao_repo.listar_pendentes(db_session)
    tipos = sorted(o.tipo for o in pendentes)
    assert tipos == ["inspecao", "iuc"]
    assert all(o.titular_id == titular.id for o in pendentes)


@pytest.mark.asyncio
async def test_job_obrigacoes_dois_veiculos_mesma_matricula_geram_quatro_obrigacoes(db_session):
    # Regressão do Finding 1 (revisão de confirmação, fix batch E): dois veiculos do mesmo
    # titular registados na MESMA data de matricula calculam datas de obrigação
    # (proxima_inspecao/proxima_iuc) idênticas. Sem veiculo_id na chave de dedupe de
    # existe_obrigacao, o segundo veiculo processado pelo job era silenciosamente descartado
    # como "duplicado" do primeiro — 2 obrigações em vez de 4, sem alerta e sem log.
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="proprio")
    matricula_partilhada = date(2022, 3, 10)
    await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Corsa", data_aquisicao=matricula_partilhada
    )
    await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Clio", data_aquisicao=matricula_partilhada
    )
    await db_session.commit()

    await sincronizar_obrigacoes_dos_ativos_ativos(db_session, referencia=date(2026, 1, 1))

    pendentes = await obrigacao_repo.listar_pendentes(db_session)
    assert len(pendentes) == 4
    assert sorted(o.tipo for o in pendentes) == ["inspecao", "inspecao", "iuc", "iuc"]
    descricoes = {o.descricao for o in pendentes}
    assert any("Corsa" in d for d in descricoes)
    assert any("Clio" in d for d in descricoes)


@pytest.mark.asyncio
async def test_job_obrigacoes_falha_num_veiculo_nao_bloqueia_os_restantes(db_session, monkeypatch):
    # Regressão: sincronizar_obrigacoes_dos_ativos_ativos não tinha isolamento por-veiculo — uma
    # exceção a meio da lista propagava-se e impedia todos os veiculos seguintes de gerarem as
    # suas obrigações. Como ativo_repo.listar_todos_ativos não tem ORDER BY, um veiculo
    # persistentemente avariado podia bloquear o agregado inteiro para sempre.
    titular = await titular_repo.criar_titular(db_session, nome="Ana", tipo="proprio")
    veiculo_avariado = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Avariado", data_aquisicao=date(2022, 3, 10)
    )
    veiculo_saudavel = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Corsa", data_aquisicao=date(2021, 5, 4)
    )
    await db_session.commit()
    # Capturados em variáveis simples ANTES de invocar a função em teste: esta chama
    # session.rollback() no ramo de falha, o que expira TODOS os objetos ORM da sessão
    # (não só o veiculo avariado) -- ler um atributo destes objetos depois disso, mesmo
    # dentro do próprio teste, rebentaria com MissingGreenlet.
    matricula_avariada = veiculo_avariado.data_aquisicao
    veiculo_avariado_id = veiculo_avariado.id
    titular_id = titular.id

    # Mock direcionado apenas à chamada do veiculo avariado (identificado pela sua matricula
    # distinta) — o veiculo saudável continua a passar pela implementação real, para testar
    # comportamento real de DB em vez de tudo mockado.
    async def sincronizar_com_falha_seletiva(
        session, *, titular_id, matricula, referencia, ativo_id, ativo_nome
    ):
        if matricula == matricula_avariada:
            raise RuntimeError("falha simulada ao sincronizar obrigações do veiculo avariado")
        return await sincronizar_obrigacoes_ativo_real(
            session,
            titular_id=titular_id,
            matricula=matricula,
            referencia=referencia,
            ativo_id=ativo_id,
            ativo_nome=ativo_nome,
        )

    monkeypatch.setattr(
        "ava.alerts.scheduler.sincronizar_obrigacoes_ativo", sincronizar_com_falha_seletiva
    )

    # Não deve propagar a exceção do veiculo avariado.
    await sincronizar_obrigacoes_dos_ativos_ativos(db_session, referencia=date(2026, 1, 1))

    # O veiculo saudável (que pode ter sido processado antes ou depois do avariado, dada a
    # ausência de ORDER BY) gerou as suas obrigações na mesma.
    pendentes = await obrigacao_repo.listar_pendentes(db_session)
    assert sorted(o.tipo for o in pendentes) == ["inspecao", "iuc"]
    assert all(o.titular_id == titular_id for o in pendentes)

    # A falha não ficou silenciosa: foi registada como alerta ativo (A-P6), identificando o
    # veiculo concreto que falhou.
    alertas_falha = [
        a
        for a in await alerta_repo.listar_nao_enviados(db_session)
        if a.tipo == "falha_obrigacoes_ativo"
    ]
    assert len(alertas_falha) == 1
    assert str(veiculo_avariado_id) in alertas_falha[0].mensagem
