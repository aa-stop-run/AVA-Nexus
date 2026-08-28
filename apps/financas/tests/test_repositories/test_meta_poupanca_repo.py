from datetime import date
from decimal import Decimal
import pytest
from ava.repositories import meta_poupanca_repo, conta_repo, titular_repo


@pytest.mark.asyncio
async def test_criar_e_listar_metas(db_session):
    meta = await meta_poupanca_repo.criar_meta(
        db_session,
        nome="Férias de Verão",
        valor_alvo=Decimal("2000.00"),
        data_alvo=date(2027, 7, 31),
        descricao="Praia em família",
        valor_atual=Decimal("450.00"),
    )
    assert meta.id is not None
    assert meta.nome == "Férias de Verão"
    assert meta.valor_alvo == Decimal("2000.00")
    assert meta.valor_atual == Decimal("450.00")
    assert meta.ativo is True

    metas = await meta_poupanca_repo.listar_metas(db_session)
    assert len(metas) == 1
    assert metas[0].id == meta.id


@pytest.mark.asyncio
async def test_ajustar_saldo_da_meta(db_session):
    meta = await meta_poupanca_repo.criar_meta(
        db_session,
        nome="Fundo Emergência",
        valor_alvo=Decimal("5000.00"),
        valor_atual=Decimal("1000.00"),
    )
    meta_atualizada = await meta_poupanca_repo.ajustar_valor_atual(
        db_session, meta_id=meta.id, delta=Decimal("250.00")
    )
    assert meta_atualizada.valor_atual == Decimal("1250.00")


@pytest.mark.asyncio
async def test_remover_meta(db_session):
    meta = await meta_poupanca_repo.criar_meta(
        db_session,
        nome="Obras",
        valor_alvo=Decimal("3000.00"),
    )
    await meta_poupanca_repo.remover_meta(db_session, meta.id)
    metas = await meta_poupanca_repo.listar_metas(db_session)
    assert len(metas) == 0
