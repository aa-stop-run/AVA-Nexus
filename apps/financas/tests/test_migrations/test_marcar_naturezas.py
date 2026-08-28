"""O retrofit das naturezas nas categorias que já existem numa base de dados antiga.

Vive num módulo importável (não dentro do ficheiro da migração) pela mesma razão que
`backfill_ativo_valor`: uma migração não é importável a partir de um teste sem arrastar o
ambiente Alembic inteiro, e a lógica de marcação é exatamente aquilo que precisa de cobertura.
"""

import pytest
from sqlalchemy import text

from ava.financas.categorias_iniciais import marcar_naturezas
from ava.repositories import categoria_repo


async def _correr_backfill(db_session):
    conn = await db_session.connection()
    return await conn.run_sync(marcar_naturezas)


@pytest.mark.asyncio
async def test_marca_por_nome_ignorando_o_grupo(db_session):
    # "Juros de crédito" existe no seed em "Encargos financeiros", mas o utilizador criou uma
    # categoria com o MESMO nome em "Habitação". Marcar por (grupo, nome) deixava a segunda por
    # marcar; marcar por nome acerta nas duas. É o caso real que motivou a decisão (spec §3.2).
    grupo_a = await categoria_repo.criar_grupo(db_session, nome="Encargos financeiros")
    grupo_b = await categoria_repo.criar_grupo(db_session, nome="Habitação")
    cat_a = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo_a.id, nome="Juros de crédito", tipo="despesa", natureza="variavel"
    )
    cat_b = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo_b.id, nome="Juros de crédito", tipo="despesa", natureza="variavel"
    )
    await db_session.commit()

    await _correr_backfill(db_session)

    await db_session.refresh(cat_a)
    await db_session.refresh(cat_b)
    assert cat_a.natureza == "fixa"
    assert cat_b.natureza == "fixa"


@pytest.mark.asyncio
async def test_categoria_fora_do_seed_fica_no_default_seguro(db_session):
    # Controlo positivo dos dois lados: não basta afirmar que não ficou marcada — tem de ficar
    # com o default CERTO, e os defaults são assimétricos de propósito (spec §3.3).
    grupo = await categoria_repo.criar_grupo(db_session, nome="Inventado")
    despesa = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Drone", tipo="despesa", natureza="fixa"
    )
    receita = await categoria_repo.criar_categoria(
        db_session, grupo_id=grupo.id, nome="Aluguer do drone", tipo="receita", natureza="recorrente"
    )
    await db_session.commit()

    await _correr_backfill(db_session)

    await db_session.refresh(despesa)
    await db_session.refresh(receita)
    assert despesa.natureza == "variavel"
    assert receita.natureza == "extraordinario"


@pytest.mark.asyncio
async def test_nenhuma_categoria_fica_com_natureza_invalida_para_o_seu_tipo(db_session):
    from ava.financas.categorias_iniciais import semear_categorias

    conn = await db_session.connection()
    await conn.run_sync(semear_categorias)
    await _correr_backfill(db_session)

    linhas = (await db_session.execute(text("SELECT tipo, natureza FROM categoria"))).all()
    assert len(linhas) == 58
    for tipo, natureza in linhas:
        if tipo == "receita":
            assert natureza in ("recorrente", "extraordinario")
        else:
            assert natureza in ("fixa", "variavel", "poupanca")
