import pytest
from httpx import ASGITransport, AsyncClient
from hub.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_health_sync_sem_token_rejeita(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/saude/sync/health-connect", json={"passos": 5000})
        assert res.status_code == 401
        assert "Token" in res.json()["detail"]


@pytest.mark.asyncio
async def test_health_sync_com_token_valido(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "titular": "aa-stop-run",
            "data_referencia": "2026-08-27",
            "sono": {
                "minutos_total": 480,
                "score": 85,
                "fases": {"profundo_minutos": 95, "rem_minutos": 100},
            },
            "atividade": {
                "passos": 8500,
            },
            "cardiovascular": {
                "bpm_repouso": 55,
                "bpm_medio": 70,
            },
        }
        res = await client.post(
            "/api/saude/sync/health-connect",
            json=payload,
            headers={"X-AVA-Device-Token": "ava-mobile-device-token-2026"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["data"] == "2026-08-27"


@pytest.mark.asyncio
async def test_download_apk_endpoint_existe(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/downloads/ava-mobile.apk")
        assert res.status_code == 200
        assert "application/vnd.android.package-archive" in res.headers["content-type"]
        assert len(res.content) > 0
