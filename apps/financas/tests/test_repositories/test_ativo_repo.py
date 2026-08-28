from datetime import date
from decimal import Decimal

import pytest

from ava.repositories import titular_repo, ativo_repo


@pytest.mark.asyncio
async def test_criar_ativo_e_listar_todos_ativos(db_session):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")

    await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, tipo="carro", nome="Corsa", data_aquisicao=date(2022, 3, 10)
    )
    await ativo_repo.criar_ativo(
        db_session,
        titular_id=titular.id,
        tipo="carro", nome="Sold vehicle",
        data_aquisicao=date(2015, 1, 1),
        ativo_status=False,
    )
    await db_session.commit()

    ativos = await ativo_repo.listar_todos_ativos(db_session)

    assert len(ativos) == 1
    assert ativos[0].nome == "Corsa"
    assert ativos[0].data_aquisicao == date(2022, 3, 10)
    assert ativos[0].titular_id == titular.id


@pytest.mark.asyncio
async def test_valor_em_data_projeta_a_partir_da_observacao_mais_recente(db_session):
    from ava.repositories import ativo_valor_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2025, 1, 1), valor=Decimal("10000.00")
    )
    await db_session.commit()

    resultado = await ativo_repo.valor_em_data(db_session, ativo, date(2026, 1, 1))

    assert resultado.e_projetado is True
    assert resultado.data_observacao == date(2025, 1, 1)
    assert Decimal("8499") <= resultado.valor <= Decimal("8501")


@pytest.mark.asyncio
async def test_valor_na_data_exata_da_observacao_nao_e_projetado(db_session):
    from ava.repositories import ativo_valor_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2026, 1, 1), valor=Decimal("8000.00")
    )
    await db_session.commit()

    resultado = await ativo_repo.valor_em_data(db_session, ativo, date(2026, 1, 1))

    assert resultado.e_projetado is False
    assert resultado.valor == Decimal("8000.00")


@pytest.mark.asyncio
async def test_avaliacao_nova_reinicia_a_curva(db_session):
    # A projeção parte SEMPRE de uma observação, nunca de outra projeção — sem isso o erro
    # acumulava-se a cada ponto.
    from ava.repositories import ativo_valor_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2020, 1, 1), valor=Decimal("30000.00")
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2026, 1, 1), valor=Decimal("9000.00")
    )
    await db_session.commit()

    resultado = await ativo_repo.valor_em_data(db_session, ativo, date(2026, 1, 1))

    assert resultado.valor == Decimal("9000.00")
    assert resultado.data_observacao == date(2026, 1, 1)


@pytest.mark.asyncio
async def test_ativo_sem_avaliacoes_nao_tem_valor(db_session):
    # None e não zero: "não sei quanto vale" não é "vale nada".
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    await db_session.commit()

    assert await ativo_repo.valor_em_data(db_session, ativo, date(2026, 1, 1)) is None


@pytest.mark.asyncio
async def test_valor_antes_da_primeira_avaliacao_e_desconhecido(db_session):
    from ava.repositories import ativo_valor_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Corsa", tipo="carro"
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2026, 1, 1), valor=Decimal("8000.00")
    )
    await db_session.commit()

    assert await ativo_repo.valor_em_data(db_session, ativo, date(2025, 1, 1)) is None


@pytest.mark.asyncio
async def test_taxa_do_ativo_ganha_a_do_tipo(db_session):
    from ava.repositories import ativo_valor_repo

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    ativo = await ativo_repo.criar_ativo(
        db_session, titular_id=titular.id, nome="Clássico", tipo="carro",
        taxa_anual=Decimal("0.05"),
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2025, 1, 1), valor=Decimal("10000.00")
    )
    await db_session.commit()

    resultado = await ativo_repo.valor_em_data(db_session, ativo, date(2026, 1, 1))

    # Valoriza em vez de depreciar, apesar de o tipo "carro" ter omissão negativa.
    assert resultado.valor > Decimal("10000.00")
