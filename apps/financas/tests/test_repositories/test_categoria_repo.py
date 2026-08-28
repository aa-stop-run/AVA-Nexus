import pytest
from sqlalchemy.exc import IntegrityError

from ava.repositories import categoria_repo


@pytest.mark.asyncio
async def test_listar_grupos_com_categorias_agrupa_e_filtra_por_tipo(db_session):
    habitacao = await categoria_repo.criar_grupo(db_session, nome="Habitação", ordem=1)
    rendimentos = await categoria_repo.criar_grupo(db_session, nome="Rendimentos", ordem=2)
    await categoria_repo.criar_categoria(
        db_session, grupo_id=habitacao.id, nome="Eletricidade", tipo="despesa", natureza="variavel", unidade_contador="kWh"
    )
    await categoria_repo.criar_categoria(db_session, grupo_id=habitacao.id, nome="Renda", tipo="despesa", natureza="variavel")
    await categoria_repo.criar_categoria(
        db_session, grupo_id=rendimentos.id, nome="Salário", tipo="receita", natureza="extraordinario"
    )
    await db_session.commit()

    so_despesa = await categoria_repo.listar_grupos_com_categorias(db_session, tipo="despesa")
    nomes_grupos = [grupo.nome for grupo, _ in so_despesa]
    assert nomes_grupos == ["Habitação"]  # Rendimentos não tem categorias de despesa
    assert sorted(c.nome for c in so_despesa[0][1]) == ["Eletricidade", "Renda"]

    todos = await categoria_repo.listar_grupos_com_categorias(db_session)
    assert [grupo.nome for grupo, _ in todos] == ["Habitação", "Rendimentos"]  # por ordem


@pytest.mark.asyncio
async def test_listar_todos_os_grupos_com_categorias_inclui_grupos_vazios(db_session):
    habitacao = await categoria_repo.criar_grupo(db_session, nome="Habitação", ordem=1)
    vazio = await categoria_repo.criar_grupo(db_session, nome="Recém-criado", ordem=2)
    await categoria_repo.criar_categoria(db_session, grupo_id=habitacao.id, nome="Renda", tipo="despesa", natureza="variavel")
    await db_session.commit()

    todos = await categoria_repo.listar_todos_os_grupos_com_categorias(db_session)

    assert [grupo.nome for grupo, _ in todos] == ["Habitação", "Recém-criado"]
    categorias_por_nome_do_grupo = {grupo.nome: categorias for grupo, categorias in todos}
    assert [c.nome for c in categorias_por_nome_do_grupo["Habitação"]] == ["Renda"]
    assert categorias_por_nome_do_grupo["Recém-criado"] == []


@pytest.mark.asyncio
async def test_obter_por_nomes_encontra_a_categoria(db_session):
    grupo = await categoria_repo.criar_grupo(db_session, nome="Transportes")
    await categoria_repo.criar_categoria(db_session, grupo_id=grupo.id, nome="Fuel Type", tipo="despesa", natureza="variavel")
    await db_session.commit()

    encontrada = await categoria_repo.obter_por_nomes(db_session, grupo="Transportes", nome="Fuel Type")
    assert encontrada is not None
    assert encontrada.tipo == "despesa"

    assert await categoria_repo.obter_por_nomes(db_session, grupo="Transportes", nome="Inexistente") is None


@pytest.mark.asyncio
async def test_nome_repetido_no_mesmo_grupo_e_rejeitado(db_session):
    grupo = await categoria_repo.criar_grupo(db_session, nome="Saúde")
    await categoria_repo.criar_categoria(db_session, grupo_id=grupo.id, nome="Consultas", tipo="despesa", natureza="variavel")
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await categoria_repo.criar_categoria(db_session, grupo_id=grupo.id, nome="Consultas", tipo="despesa", natureza="variavel")
        await db_session.commit()


@pytest.mark.asyncio
async def test_natureza_incompativel_com_o_tipo_e_rejeitada_pela_check_constraint(db_session):
    # É o mecanismo central que a Tarefa 1 introduz (ck_categoria_natureza, ver o comentário em
    # models/categoria.py): "fixa" é uma natureza de despesa, nunca de receita. Sem este teste, a
    # constraint podia ser removida ou desalinhada numa migração futura distraída e nada acusaria
    # — uma categoria de receita ficaria "fixa" por um POST mal formado, exatamente o cenário que
    # o comentário do modelo descreve.
    grupo = await categoria_repo.criar_grupo(db_session, nome="Rendimentos Inválidos")

    with pytest.raises(IntegrityError):
        await categoria_repo.criar_categoria(
            db_session, grupo_id=grupo.id, nome="Salário Mal Classificado", tipo="receita", natureza="fixa"
        )
        await db_session.flush()
