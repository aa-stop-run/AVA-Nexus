import pytest
from datetime import date
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from casa.models.base import Base
from casa.models.equipamento import EquipamentoCasa
from casa.models.manutencao import ManutencaoCasa
from casa.repositories import casa_repo


@pytest.fixture
async def test_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_criar_e_obter_equipamento(test_session):
    eq = await casa_repo.criar_equipamento(
        test_session,
        nome="Smartwatch Membersung Watch 8",
        marca="Membersung",
        modelo="SM-L330NZSAEUB",
        categoria="eletronica",
        divisao_casa="Escritório",
        data_compra=date(2026, 8, 19),
        valor_compra=Decimal("204.90"),
        anos_garantia=3,
    )
    assert eq.id is not None
    assert eq.data_fim_garantia == date(2029, 8, 19)
    assert eq.estado_garantia == "em_garantia"
    assert eq.dias_restantes_garantia > 365

    lista = await casa_repo.obter_equipamentos(test_session)
    assert len(lista) == 1
    assert lista[0].nome == "Smartwatch Membersung Watch 8"


@pytest.mark.asyncio
async def test_criar_e_obter_manutencao(test_session):
    m = await casa_repo.criar_manutencao(
        test_session,
        titulo="Revisão Caldeira",
        divisao_casa="Lavandaria",
        periodicidade_meses=12,
        proxima_data=date(2026, 10, 20),
        custo_estimado=Decimal("85.00"),
    )
    assert m.id is not None
    assert m.concluida is False
    assert m.titulo == "Revisão Caldeira"

    lista = await casa_repo.obter_manutencoes(test_session)
    assert len(lista) == 1
