from datetime import date
from decimal import Decimal

import pytest

from ava.repositories import ativo_repo, ativo_valor_repo, titular_repo


async def _ativo(db_session, tipo="carro"):
    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    ativo = await ativo_repo.criar_ativo(db_session, titular_id=titular.id, nome="Corsa", tipo=tipo)
    await db_session.commit()
    return ativo


@pytest.mark.asyncio
async def test_registar_e_obter_observacao_mais_recente(db_session):
    ativo = await _ativo(db_session)
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2025, 1, 1), valor=Decimal("10000.00")
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2026, 1, 1), valor=Decimal("8000.00")
    )
    await db_session.commit()

    obs = await ativo_valor_repo.obter_valor_em_data(db_session, ativo.id, date(2026, 6, 1))
    assert obs.valor == Decimal("8000.00")
    assert obs.data == date(2026, 1, 1)


@pytest.mark.asyncio
async def test_obter_valor_em_data_anterior_a_tudo_devolve_none(db_session):
    ativo = await _ativo(db_session)
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2026, 1, 1), valor=Decimal("8000.00")
    )
    await db_session.commit()

    assert await ativo_valor_repo.obter_valor_em_data(db_session, ativo.id, date(2025, 6, 1)) is None


@pytest.mark.asyncio
async def test_registar_na_mesma_data_substitui_em_vez_de_duplicar(db_session):
    # Duas avaliações no mesmo dia são uma correção de quem se enganou, não dois factos.
    ativo = await _ativo(db_session)
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2026, 3, 1), valor=Decimal("8000.00")
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2026, 3, 1), valor=Decimal("8500.00")
    )
    await db_session.commit()

    historico = await ativo_valor_repo.listar_por_ativo(db_session, ativo.id)
    assert len(historico) == 1
    assert historico[0].valor == Decimal("8500.00")


@pytest.mark.asyncio
async def test_listar_por_ativo_ordena_da_mais_recente_para_a_mais_antiga(db_session):
    ativo = await _ativo(db_session)
    for ano, valor in ((2024, "12000.00"), (2026, "8000.00"), (2025, "10000.00")):
        await ativo_valor_repo.registar_valor(
            db_session, ativo_id=ativo.id, data=date(ano, 1, 1), valor=Decimal(valor)
        )
    await db_session.commit()

    historico = await ativo_valor_repo.listar_por_ativo(db_session, ativo.id)
    assert [h.data.year for h in historico] == [2026, 2025, 2024]


@pytest.mark.asyncio
async def test_apagar_remove_so_a_avaliacao_indicada(db_session):
    ativo = await _ativo(db_session)
    a = await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2025, 1, 1), valor=Decimal("10000.00")
    )
    await ativo_valor_repo.registar_valor(
        db_session, ativo_id=ativo.id, data=date(2026, 1, 1), valor=Decimal("8000.00")
    )
    await db_session.commit()

    assert await ativo_valor_repo.apagar(db_session, a.id) is True
    await db_session.commit()

    historico = await ativo_valor_repo.listar_por_ativo(db_session, ativo.id)
    assert [h.data.year for h in historico] == [2026]
