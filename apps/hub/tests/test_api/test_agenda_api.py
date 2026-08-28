import pytest
from httpx import ASGITransport, AsyncClient
from hub.main import create_app
from hub.db import get_session


@pytest.fixture
def app():
    app_instance = create_app()

    async def override_get_session():
        class MockSession:
            async def execute(self, *args, **kwargs):
                class MockResult:
                    def scalar(self):
                        return 0
                    def mappings(self):
                        return []
                    @property
                    def rowcount(self):
                        return 1
                return MockResult()

            async def commit(self):
                pass
                
        yield MockSession()

    app_instance.dependency_overrides[get_session] = override_get_session
    return app_instance


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_get_agenda_endpoint(client):
    resp = await client.get("/api/agenda?mes=8&ano=2026")
    assert resp.status_code == 200
    dados = resp.json()
    assert "mes" in dados
    assert "ano" in dados
    assert "eventos" in dados
    assert "dias_com_eventos" in dados


@pytest.mark.asyncio
async def test_create_and_delete_evento_endpoint(client, monkeypatch):
    # Mock criar_evento_calendario
    from hub.api import agenda_api
    
    async def mock_criar(*args, **kwargs):
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "titulo": "Reunião de Equipa",
            "data_inicio": "2026-08-28T14:00:00Z"
        }
        
    async def mock_remover(*args, **kwargs):
        return True

    monkeypatch.setattr(agenda_api, "criar_evento_calendario", mock_criar)
    monkeypatch.setattr(agenda_api, "remover_evento_calendario", mock_remover)

    # Post
    resp = await client.post("/api/agenda/evento", json={
        "titulo": "Reunião de Equipa",
        "data_inicio": "2026-08-28T14:00:00Z",
        "tipo": "pessoal"
    })
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "ok"
    assert "evento" in res_data

    # Delete evento pessoal
    resp_del = await client.delete("/api/agenda/evento/11111111-1111-1111-1111-111111111111")
    assert resp_del.status_code == 200
    assert resp_del.json()["removido"] is True

    # Delete consulta de saúde (prefixo saude-)
    resp_del_saude = await client.delete("/api/agenda/evento/saude-22222222-2222-2222-2222-222222222222")
    assert resp_del_saude.status_code == 200
    assert resp_del_saude.json()["removido"] is True

    # Delete evento do Google Calendar (prefixo google-)
    resp_del_google = await client.delete("/api/agenda/evento/google-test-uid-12345")
    assert resp_del_google.status_code == 200
    assert resp_del_google.json()["removido"] is True


@pytest.mark.asyncio
async def test_update_evento_endpoint(client, monkeypatch):
    from hub.api import agenda_api

    async def mock_atualizar(*args, **kwargs):
        return {"id": "11111111-1111-1111-1111-111111111111", "status": "atualizado"}

    monkeypatch.setattr(agenda_api, "atualizar_evento_calendario", mock_atualizar)

    resp = await client.put("/api/agenda/evento/11111111-1111-1111-1111-111111111111", json={
        "titulo": "Reunião de Equipa Atualizada",
        "local": "Escritório"
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_get_ical_feed_endpoint(client):
    resp = await client.get("/api/agenda/feed.ics")
    assert resp.status_code == 200
    assert "text/calendar" in resp.headers.get("content-type", "")
    assert "BEGIN:VCALENDAR" in resp.text
    assert "END:VCALENDAR" in resp.text



