import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from ava.db import get_session
from ava.main import create_app
from tests.fabricas import criar_categoria


def _client_para(db_session):
    app = create_app()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_marcar_natureza_grava_e_devolve_a_celula(db_session):
    categoria = await criar_categoria(
        db_session, nome="ATL", tipo="despesa", natureza="variavel"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/configuracoes/categorias/{categoria.id}/natureza", data={"natureza": "fixa"}
        )

    assert resposta.status_code == 200
    # `_natureza_cell.html` renderiza TODAS as opções válidas de naturezas_de(categoria.tipo)
    # para a categoria — "Fixa" aparece sempre como opção de uma categoria de despesa, gravada
    # ou não. A asserção tem de verificar o atributo `selected`, com um controlo negativo ao
    # lado: sem isto, o teste passava mesmo que `selected` desaparecesse por completo do HTML.
    assert 'value="fixa" selected' in resposta.text
    assert 'value="variavel" selected' not in resposta.text
    await db_session.refresh(categoria)
    assert categoria.natureza == "fixa"


@pytest.mark.asyncio
async def test_natureza_incompativel_com_o_tipo_e_recusada(db_session):
    # "recorrente" é natureza de receita. Numa despesa tem de ser recusada ANTES de chegar à
    # base de dados, para dar um erro amigável em vez de um IntegrityError da ck_categoria_natureza.
    categoria = await criar_categoria(
        db_session, nome="Renda", tipo="despesa", natureza="fixa"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/configuracoes/categorias/{categoria.id}/natureza",
            data={"natureza": "recorrente"},
        )

    assert resposta.status_code == 422
    await db_session.refresh(categoria)
    assert categoria.natureza == "fixa"


@pytest.mark.asyncio
async def test_categoria_inexistente_da_404(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.post(
            f"/configuracoes/categorias/{uuid.uuid4()}/natureza", data={"natureza": "fixa"}
        )

    assert resposta.status_code == 404


@pytest.mark.asyncio
async def test_pagina_mostra_a_natureza_de_cada_categoria(db_session):
    await criar_categoria(db_session, nome="Renda", tipo="despesa", natureza="fixa")
    await criar_categoria(
        db_session, nome="Supermercado", tipo="despesa", natureza="variavel"
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.get("/configuracoes/categorias")

    assert resposta.status_code == 200
    assert "Fixa" in resposta.text
    assert "Variável" in resposta.text


@pytest.mark.asyncio
async def test_criar_categoria_com_natureza_invalida_e_recusada(db_session):
    from ava.repositories import categoria_repo

    grupo = await categoria_repo.criar_grupo(db_session, nome="Grupo Teste")
    await db_session.commit()

    async with _client_para(db_session) as client:
        resposta = await client.post(
            "/configuracoes/categorias",
            data={
                "grupo_id": str(grupo.id),
                "nome": "Inventada",
                "tipo": "despesa",
                "natureza": "recorrente",
            },
        )

    assert resposta.status_code == 422
    assert "Natureza" in resposta.text


# --- Redesenho visual (Task 6) ---


@pytest.mark.asyncio
async def test_criacao_de_categoria_usa_cartao_em_vez_de_grid_fixo(db_session):
    async with _client_para(db_session) as client:
        resposta = await client.get("/configuracoes/categorias")

    assert resposta.status_code == 200
    assert 'class="cartao-registo"' in resposta.text
    assert "grid-cols-2" not in resposta.text
