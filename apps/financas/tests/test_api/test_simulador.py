from decimal import Decimal
import pytest
from httpx import ASGITransport, AsyncClient

from ava.db import get_session
from ava.main import create_app


def _client_para(db_session):
    app = create_app()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_get_simulador_page_retorna_200(db_session):
    from ava.repositories import conta_repo, titular_repo, saldo_historico_repo
    from datetime import date

    titular = await titular_repo.criar_titular(db_session, nome="Nuno", tipo="proprio")
    conta_divida = await conta_repo.criar_conta(
        db_session,
        titular_id=titular.id,
        instituicao="BPI",
        tipo="divida",
        nome="Mortgage & Loans",
    )
    await saldo_historico_repo.registar_saldo(
        db_session,
        conta_id=conta_divida.id,
        data=date(2026, 8, 1),
        valor=Decimal("142500.00"),
    )
    await db_session.commit()

    async with _client_para(db_session) as client:
        resp = await client.get("/simulador")

    assert resp.status_code == 200
    assert "Simulador de Amortização" in resp.text
    assert "Mortgage & Loans" in resp.text
    assert "142.500,00" in resp.text or "142500" in resp.text


@pytest.mark.asyncio
async def test_post_simulador_calcular_retorna_resultados_comparativos(db_session):
    async with _client_para(db_session) as client:
        resp = await client.post(
            "/simulador/calcular",
            data={
                "capital_divida": "150000.00",
                "taxa_anual": "3.5",
                "prazo_meses": "300",
                "valor_amortizar": "5000.00",
                "taxa_comissao": "0.5",
            },
        )
    assert resp.status_code == 200
    assert "Reduzir Prestação" in resp.text
    assert "Reduzir Prazo" in resp.text
    assert "Poupança Total em Juros" in resp.text
