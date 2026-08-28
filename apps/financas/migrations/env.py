import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from ava.config import get_settings
from ava.models import (  # noqa: F401  (register tables)
    alerta,
    categoria,
    conta,
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
    ativo,
    ativo_valor,
)
from ava.models.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


asyncio.run(run_migrations_online())
