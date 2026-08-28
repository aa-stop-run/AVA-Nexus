import pytest
from httpx import ASGITransport, AsyncClient
from saude.main import create_app
from saude.db import get_session


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
async def test_endpoints_medicamentos(client: AsyncClient):
    # 1. Criar Medicamento
    payload = {
        "titular": "aa-stop-run",
        "nome": "Sertralina",
        "principio_ativo": "Cloridrato de Sertralina",
        "dosagem": "50 mg",
        "stock_atual": 10,
        "stock_minimo_alerta": 5,
        "forma_farmaceutica": "pill",
        "unidade_medida": "pills",
        "instrucoes_toma": "Tomar após o pequeno-almoço",
        "horarios": [{"hora": "08:30", "quantidade_dose": 1.0, "dias_semana": "todos"}]
    }
    resp = await client.post("/api/saude/medicamentos", json=payload)
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["nome"] == "Sertralina"
    assert data["stock_atual"] == 10
    med_id = data["id"]

    # 2. Listar Medicamentos
    resp_list = await client.get("/api/saude/medicamentos")
    assert resp_list.status_code == 200
    meds = resp_list.json()
    assert len(meds) >= 1
    assert any(m["id"] == med_id for m in meds)

    # 3. Obter Schedule Sync para Android
    resp_sync = await client.get("/api/saude/medicamentos/schedule-sync?dias=7")
    assert resp_sync.status_code == 200
    schedule = resp_sync.json()
    assert len(schedule) >= 7
    assert schedule[0]["medicamento_id"] == med_id

    # 4. Registar Toma
    resp_toma = await client.post(f"/api/saude/medicamentos/{med_id}/toma", json={
        "registado_via": "mobile_notification"
    })
    assert resp_toma.status_code == 200
    assert resp_toma.json()["stock_atual"] == 9

    # 5. Repor Stock
    resp_repor = await client.post(f"/api/saude/medicamentos/{med_id}/repor-stock", json={
        "quantidade": 30
    })
    assert resp_repor.status_code == 200
    assert resp_repor.json()["stock_atual"] == 39

    # 6. Alertas de Low Stock
    resp_alerta = await client.get("/api/saude/medicamentos/alertas-stock")
    assert resp_alerta.status_code == 200
