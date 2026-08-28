from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from ava.financas.backfill_ativo_valor import backfill_ativo_valor
from ava.repositories import titular_repo


@pytest.fixture(autouse=True)
async def coluna_legada(db_session):
    """Repõe `ativo.valor_atual` só para estes testes.

    A coluna foi removida do modelo (Task 9), mas o backfill continua a ter de funcionar em
    qualquer base de dados que ainda esteja atrasada — é para essas que a migração existe.
    Delete estes testes deixaria essa garantia sem cobertura.
    """
    await db_session.execute(
        text("ALTER TABLE ativo ADD COLUMN IF NOT EXISTS valor_atual NUMERIC(12,2)")
    )
    await db_session.commit()


async def _correr_backfill(db_session):
    conn = await db_session.connection()
    return await conn.run_sync(backfill_ativo_valor)


@pytest.mark.asyncio
async def test_backfill_data_o_valor_de_hoje_e_nao_da_aquisicao(db_session):
    # A parte fácil de errar: valor_atual é o que o utilizador acredita que o bem vale HOJE.
    # Datá-lo da aquisição faria a app depreciá-lo outra vez desde essa data — um carro de 2022
    # a -15%/ano colapsaria para metade no instante da migração.
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    await db_session.execute(
        text(
            "INSERT INTO ativo (id, titular_id, nome, tipo, valor_atual, data_aquisicao, ativo) "
            "VALUES (gen_random_uuid(), :t, 'Corsa', 'carro', 8000.00, '2022-03-10', true)"
        ),
        {"t": titular.id},
    )
    await db_session.commit()

    assert await _correr_backfill(db_session) == 1
    await db_session.commit()

    linhas = (await db_session.execute(text("SELECT data, valor, origem FROM ativo_valor"))).all()
    assert len(linhas) == 1
    assert linhas[0][0] == date.today()
    assert linhas[0][1] == Decimal("8000.00")
    assert linhas[0][2] == "observado"


@pytest.mark.asyncio
async def test_backfill_ignora_ativos_sem_valor(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    await db_session.execute(
        text(
            "INSERT INTO ativo (id, titular_id, nome, tipo, valor_atual, ativo) "
            "VALUES (gen_random_uuid(), :t, 'Sem valor', 'outro', 0.00, true)"
        ),
        {"t": titular.id},
    )
    await db_session.commit()

    assert await _correr_backfill(db_session) == 0


@pytest.mark.asyncio
async def test_backfill_e_idempotente(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    await db_session.flush()
    await db_session.execute(
        text(
            "INSERT INTO ativo (id, titular_id, nome, tipo, valor_atual, ativo) "
            "VALUES (gen_random_uuid(), :t, 'Corsa', 'carro', 8000.00, true)"
        ),
        {"t": titular.id},
    )
    await db_session.commit()

    assert await _correr_backfill(db_session) == 1
    await db_session.commit()
    assert await _correr_backfill(db_session) == 0
    await db_session.commit()

    total = (await db_session.execute(text("SELECT count(*) FROM ativo_valor"))).scalar()
    assert total == 1
