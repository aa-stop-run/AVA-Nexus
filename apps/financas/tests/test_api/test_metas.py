from decimal import Decimal
import pytest
from httpx import ASGITransport, AsyncClient

from ava.db import get_session
from ava.main import create_app
from ava.repositories import meta_poupanca_repo


def _client_para(db_session):
    app = create_app()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_get_metas_page_retorna_200(db_session):
    await meta_poupanca_repo.criar_meta(
        db_session,
        nome="Férias",
        valor_alvo=Decimal("1500.00"),
        valor_atual=Decimal("300.00"),
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resp = await client.get("/metas")

    assert resp.status_code == 200
    assert "Metas de Poupança" in resp.text
    assert "Férias" in resp.text


@pytest.mark.asyncio
async def test_post_criar_meta(db_session):
    async with _client_para(db_session) as client:
        resp = await client.post(
            "/metas",
            data={
                "nome": "Carro Novo",
                "valor_alvo": "10000.00",
                "valor_atual": "2000.00",
                "data_alvo": "2028-12-31",
                "descricao": "Poupança para entrada",
            },
            follow_redirects=True,
        )
    assert resp.status_code == 200
    assert "Carro Novo" in resp.text


@pytest.mark.asyncio
async def test_post_ajustar_saldo_meta(db_session):
    meta = await meta_poupanca_repo.criar_meta(
        db_session,
        nome="Obras",
        valor_alvo=Decimal("3000.00"),
        valor_atual=Decimal("500.00"),
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resp = await client.post(
            f"/metas/{meta.id}/ajustar-saldo",
            data={"delta": "200.00"},
        )
    assert resp.status_code == 200
    assert "700,00" in resp.text or "700" in resp.text


@pytest.mark.asyncio
async def test_post_apagar_meta(db_session):
    meta = await meta_poupanca_repo.criar_meta(
        db_session,
        nome="Meta a Delete",
        valor_alvo=Decimal("1000.00"),
        valor_atual=Decimal("100.00"),
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resp = await client.post(
            f"/metas/{meta.id}/apagar",
            follow_redirects=True,
        )
    assert resp.status_code == 200
    assert "Meta a Delete" not in resp.text
