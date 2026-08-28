import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ava:ava@localhost:5433/ava_test")
os.environ.setdefault("PAPERLESS_URL", "http://localhost:8010")
os.environ.setdefault("PAPERLESS_TOKEN", "test-token")
os.environ.setdefault("WORKER_SHARED_TOKEN", "test-worker-token")
os.environ.setdefault("LLM_BASE_URL", "http://localhost:8080")

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ava.config import get_settings
from ava.models import (  # noqa: F401  (register tables on Base.metadata)
    alerta,
    ativo,
    ativo_valor,
    categoria,
    conta,
    contrato,
    divergencia_aceite,
    documento,
    fornecedor,
    grupo_categoria,
    item_fila,
    linha_extrato,
    meta_poupanca,
    movimento,
    movimento_linha,
    obrigacao,
    orcamento,
    recorrente,
    ressarcimento,
    saldo_historico,
    titular,
)
from ava.models.base import Base


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
