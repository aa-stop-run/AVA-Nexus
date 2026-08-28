import pytest
from httpx import ASGITransport, AsyncClient
from saude.main import create_app
from saude.db import get_session
from saude.repositories.medicamento_repo import MedicamentoRepository


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
async def test_dashboard_render_medicamentos(client: AsyncClient, db_session):
    repo = MedicamentoRepository(db_session)
    await repo.criar_medicamento(
        titular="aa-stop-run",
        nome="Sertralina",
        dosagem="50 mg",
        stock_atual=20,
        stock_minimo_alerta=5,
        horarios=[{"hora": "08:30", "quantidade_dose": 1.0}]
    )

    # Testar página principal do dashboard
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Medicamentos" in resp.text or "Farmácia" in resp.text

    # Testar página dedicada de farmácia e medicamentos
    resp_meds = await client.get("/medicamentos")
    assert resp_meds.status_code == 200
    assert "Sertralina" in resp_meds.text
    assert "50 mg" in resp_meds.text
    assert "aa-stop-run" in resp_meds.text
