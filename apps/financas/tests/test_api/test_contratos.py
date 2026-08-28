import pytest
from httpx import ASGITransport, AsyncClient

from ava.db import get_session
from ava.main import create_app
from tests.fabricas import criar_titular_e_conta


def _client_para(db_session):
    app = create_app()

    async def override():
        yield db_session

    app.dependency_overrides[get_session] = override
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_listar_contratos_view_200(db_session):
    client = _client_para(db_session)
    async with client:
        response = await client.get("/contratos")
        assert response.status_code == 200
        assert "Contratos, Seguros & Warranties" in response.text


@pytest.mark.asyncio
async def test_form_contrato_novo_view_200(db_session):
    client = _client_para(db_session)
    async with client:
        response = await client.get("/contratos/novo")
        assert response.status_code == 200
        assert "Registar Contrato, Seguro ou Garantia" in response.text


@pytest.mark.asyncio
async def test_criar_e_desativar_contrato_post(db_session):
    titular, _ = await criar_titular_e_conta(db_session)
    await db_session.commit()

    client = _client_para(db_session)
    async with client:
        # POST /contratos/novo
        response = await client.post(
            "/contratos/novo",
            data={
                "titular_id": str(titular.id),
                "nome": "Seguro Tranquilidade Auto",
                "tipo": "seguro_auto",
                "data_inicio": "2026-01-01",
                "data_fim": "2027-01-01",
                "valor": "320,50",
                "periodicidade": "anual",
                "dias_aviso_previo": "30",
                "renovacao_automatica": "true",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].startswith("/contratos")

        # GET /contratos
        res_list = await client.get("/contratos")
        assert res_list.status_code == 200
        assert "Seguro Tranquilidade Auto" in res_list.text
