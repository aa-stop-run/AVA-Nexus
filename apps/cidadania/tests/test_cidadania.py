import pytest
from datetime import date
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from cidadania.models.base import Base
from cidadania.models.documento_identificacao import DocumentoIdentificacao
from cidadania.models.obrigacao_fiscal import ObrigacaoFiscal
from cidadania.repositories import cidadania_repo


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
async def test_criar_e_obter_documento(test_session):
    doc = await cidadania_repo.criar_documento(
        test_session,
        titular_nome="aa-stop-run",
        tipo="cartao_cidadao",
        numero="13849204 4 ZY2",
        data_validade=date(2028, 5, 14),
        entidade_emissora="IRN, IP",
    )
    assert doc.id is not None
    assert doc.nome_legivel == "Cartão de Cidadão"
    assert doc.estado_validade == "valido"
    assert doc.dias_restantes > 180

    lista = await cidadania_repo.obter_documentos(test_session, titular="aa-stop-run")
    assert len(lista) == 1
    assert lista[0].numero == "13849204 4 ZY2"


@pytest.mark.asyncio
async def test_criar_e_obter_obrigacao_fiscal(test_session):
    ob = await cidadania_repo.criar_obrigacao_fiscal(
        test_session,
        nome="Validação e-fatura",
        categoria="efatura",
        ano_fiscal=2026,
        data_limite=date(2027, 2, 25),
    )
    assert ob.id is not None
    assert ob.pago is False
    assert ob.estado in ["pendente", "urgente"]

    lista = await cidadania_repo.obter_obrigacoes_fiscais(test_session, ano=2026)
    assert len(lista) == 1
