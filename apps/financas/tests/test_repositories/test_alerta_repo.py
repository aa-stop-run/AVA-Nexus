import pytest
from sqlalchemy import select

from ava.models.alerta import Alerta
from ava.repositories.alerta_repo import criar_se_novo


@pytest.mark.asyncio
async def test_criar_se_novo_cria_alerta(db_session):
    alerta = await criar_se_novo(
        db_session, tipo="idade_fila", chave_deduplicacao="chave-1", mensagem="mensagem"
    )
    await db_session.commit()

    assert alerta is not None
    assert alerta.chave_deduplicacao == "chave-1"
    assert alerta.enviado is False


@pytest.mark.asyncio
async def test_criar_se_novo_duplicado_e_rejeitado(db_session):
    await criar_se_novo(db_session, tipo="idade_fila", chave_deduplicacao="chave-2", mensagem="m1")
    await db_session.commit()

    resultado = await criar_se_novo(
        db_session, tipo="idade_fila", chave_deduplicacao="chave-2", mensagem="m2"
    )

    assert resultado is None


@pytest.mark.asyncio
async def test_criar_se_novo_duplicado_nao_reverte_outro_alerta_pendente_na_sessao(db_session):
    await criar_se_novo(
        db_session, tipo="idade_fila", chave_deduplicacao="chave-existente", mensagem="m1"
    )
    await db_session.commit()

    # Simula um lote com um item genuinamente novo (ainda não commitado) e um
    # duplicado (já alertado), como acontece em verificar_idade_da_fila /
    # verificar_falhas_de_ingestao ao percorrer múltiplos itens antes do commit final.
    novo_alerta = await criar_se_novo(
        db_session, tipo="idade_fila", chave_deduplicacao="chave-nova", mensagem="m2"
    )
    assert novo_alerta is not None

    duplicado = await criar_se_novo(
        db_session, tipo="idade_fila", chave_deduplicacao="chave-existente", mensagem="m3"
    )
    assert duplicado is None

    # O rollback do INSERT duplicado deve ficar confinado ao SAVEPOINT: o
    # alerta novo criado antes (ainda não commitado) tem de sobreviver na sessão.
    resultado = await db_session.execute(
        select(Alerta).where(Alerta.chave_deduplicacao == "chave-nova")
    )
    assert resultado.scalar_one_or_none() is not None
