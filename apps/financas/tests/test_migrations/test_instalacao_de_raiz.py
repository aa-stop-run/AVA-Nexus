"""Prova que `alembic upgrade head` corre do zero, numa base de dados nova e vazia.

Nenhum outro teste exerce isto: `tests/conftest.py` constrói o esquema com
`Base.metadata.create_all`, que salta a cadeia Alembic inteira. Uma migração que só funcione
numa base de dados já parcialmente migrada (como a de produção, migrada incrementalmente) passa
despercebida por toda a suite — foi exatamente isso que aconteceu quando `semear_categorias`
passou a escrever `natureza` no INSERT sem detetar que três migrações anteriores a
`c4a7e2f81b6d` a chamam antes de essa coluna existir (revisão final de ramo da margem
estrutural, achado Critical 1: `alembic upgrade head` partia-se com
`UndefinedColumnError: column "natureza" of relation "categoria" does not exist`). Este teste é
a rede de segurança que faltava — teria apanhado o bug antes de chegar à revisão final.

Cria e destrói a sua PRÓPRIA base de dados (não `ava_test`, que a fixture `db_session` usa),
para não interferir com o resto da suite. Corre `alembic upgrade head` num SUBPROCESSO e não
in-process: `ava.config.get_settings` tem `@lru_cache`, e a essa altura já foi chamado por
`tests/conftest.py` com a URL de `ava_test` — invocar `alembic.command.upgrade` no mesmo
processo devolveria sempre essa instância cacheada, ignorando a base de dados nova criada aqui.
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ava.config import get_settings

_RAIZ_DO_REPO = Path(__file__).resolve().parents[2]
_NOME_BD_NOVA = "ava_test_instalacao_raiz"


def _url_asyncpg(url_sqlalchemy: str) -> str:
    """`postgresql+asyncpg://...` → `postgresql://...`, para uso direto com o driver asyncpg."""
    return url_sqlalchemy.replace("postgresql+asyncpg://", "postgresql://", 1)


def _url_com_bd(url_sqlalchemy: str, nome_bd: str) -> str:
    """Troca só o nome da base de dados no fim do URL, preservando anfitrião/utilizador."""
    partes = urlsplit(url_sqlalchemy)
    return urlunsplit(partes._replace(path=f"/{nome_bd}"))


async def _criar_bd_vazia(url_admin_asyncpg: str, nome_bd: str) -> None:
    # CREATE DATABASE não pode correr dentro de uma transação — a ligação asyncpg crua, sem
    # `session`/`engine` do SQLAlchemy à volta, não abre uma implicitamente.
    conn = await asyncpg.connect(url_admin_asyncpg)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{nome_bd}"')
        await conn.execute(f'CREATE DATABASE "{nome_bd}"')
    finally:
        await conn.close()


async def _apagar_bd(url_admin_asyncpg: str, nome_bd: str) -> None:
    conn = await asyncpg.connect(url_admin_asyncpg)
    try:
        # Fecha ligações residuais antes do DROP: o subprocess do alembic já terminou, mas o
        # pool do SQLAlchemy usado para as asserções pode manter uma ligação viva mais um
        # instante, e DROP DATABASE falha com "database is being accessed by other users" se
        # houver alguma.
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            nome_bd,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{nome_bd}"')
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_alembic_upgrade_head_numa_bd_nova_e_vazia():
    settings = get_settings()
    url_admin_asyncpg = _url_asyncpg(settings.database_url)
    url_nova_sqlalchemy = _url_com_bd(settings.database_url, _NOME_BD_NOVA)

    await _criar_bd_vazia(url_admin_asyncpg, _NOME_BD_NOVA)
    try:
        # DATABASE_URL é como `ava.config.Settings` (e portanto `migrations/env.py`) resolvem a
        # ligação — ver `alembic.ini`, que deixa `sqlalchemy.url` vazio de propósito. O resto do
        # ambiente (PAPERLESS_URL, PAPERLESS_TOKEN, WORKER_SHARED_TOKEN, LLM_BASE_URL) já está
        # em `os.environ` porque `tests/conftest.py` os define com `setdefault` no arranque da
        # suite — o subprocesso herda-os.
        env = {**os.environ, "DATABASE_URL": url_nova_sqlalchemy}
        resultado = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(_RAIZ_DO_REPO),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert resultado.returncode == 0, (
            "alembic upgrade head falhou numa base de dados nova e vazia:\n"
            f"STDOUT:\n{resultado.stdout}\n"
            f"STDERR:\n{resultado.stderr}"
        )

        engine = create_async_engine(url_nova_sqlalchemy)
        try:
            async with engine.connect() as conn:
                total = (await conn.execute(text("SELECT count(*) FROM categoria"))).scalar_one()
                sem_natureza = (
                    await conn.execute(
                        text("SELECT count(*) FROM categoria WHERE natureza IS NULL")
                    )
                ).scalar_one()
                tem_constraint = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM pg_constraint "
                            "WHERE conname = 'ck_categoria_natureza'"
                        )
                    )
                ).scalar_one()
        finally:
            await engine.dispose()

        # O seed completo (58 categorias, spec §3.2) e o backfill (marcar_naturezas, chamado
        # pela própria migração c4a7e2f81b6d) têm de deixar a tabela coerente com a constraint
        # que a mesma migração cria a seguir.
        assert total == 58
        assert sem_natureza == 0
        assert tem_constraint == 1
    finally:
        await _apagar_bd(url_admin_asyncpg, _NOME_BD_NOVA)
