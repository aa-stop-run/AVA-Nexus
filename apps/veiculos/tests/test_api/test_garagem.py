import pytest
from datetime import date
from decimal import Decimal
from httpx import ASGITransport, AsyncClient

from veiculos.main import create_app
from veiculos.db import get_session
from veiculos.repositories import veiculo_repo


@pytest.fixture
def app(db_session):
    app_instance = create_app()

    async def override_get_session():
        yield db_session

    app_instance.dependency_overrides[get_session] = override_get_session
    return app_instance


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_get_garagem_retorna_200(client, db_session):
    await veiculo_repo.criar_veiculo(
        db_session,
        nome="Sedan 2.0 TDI",
        tipo="carro",
        matricula="12-AB-34",
        ano_matricula=2018,
        mes_matricula=5,
        km_atual=145000,
    )
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Garagem" in resp.text
    assert "Sedan 2.0 TDI" in resp.text


@pytest.mark.asyncio
async def test_post_novo_veiculo(client, db_session):
    resp = await client.post(
        "/veiculos",
        data={
            "nome": "City Hatchback 1.2",
            "tipo": "carro",
            "matricula": "56-CD-78",
            "ano_matricula": "2016",
            "mes_matricula": "9",
            "combustivel": "gasoleo",
            "km_atual": "180000",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302, 303)
    veiculos = await veiculo_repo.listar_veiculos(db_session)
    assert any(v.nome == "City Hatchback 1.2" for v in veiculos)


@pytest.mark.asyncio
async def test_get_veiculo_detalhe_e_adicionar_manutencao(client, db_session):
    v = await veiculo_repo.criar_veiculo(
        db_session,
        nome="Commuter 125cc",
        tipo="mota",
        km_atual=6000,
    )
    resp_get = await client.get(f"/veiculos/{v.id}")
    assert resp_get.status_code == 200
    assert "Commuter 125cc" in resp_get.text

    resp_post = await client.post(
        f"/veiculos/{v.id}/manutencoes",
        data={
            "data": "2026-08-10",
            "km": "6500",
            "tipo_servico": "oleo_filtros",
            "descricao": "Revisão dos 6.000 km",
            "oficina": "Oficina Motas",
            "custo": "85.00",
        },
        follow_redirects=False,
    )
    assert resp_post.status_code in (200, 302, 303)
    manutencoes = await veiculo_repo.listar_manutencoes(db_session, v.id)
    assert len(manutencoes) == 1
    assert manutencoes[0].descricao == "Revisão dos 6.000 km"
