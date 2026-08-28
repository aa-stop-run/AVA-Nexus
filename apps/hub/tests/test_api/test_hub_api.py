import pytest
from httpx import ASGITransport, AsyncClient
from hub.main import create_app
from hub.db import get_session


@pytest.fixture
def app():
    app_instance = create_app()

    async def override_get_session():
        class MockSession:
            async def commit(self):
                pass
            async def execute(self, *args, **kwargs):
                query_str = str(args[0]) if args else ""
                class MockResult:
                    def scalar(self):
                        return 0
                    def scalars(self):
                        class MockScalars:
                            def all(self):
                                return []
                        return MockScalars()
                    def mappings(self):
                        class MockMappings:
                            def first(self):
                                if "seguro_auto" in query_str:
                                    from datetime import date
                                    return {
                                        "nome": "Seguro Auto: Renault Mégane (Divina Seguros)",
                                        "numero_referencia": "P/5085/142001304364",
                                        "data_fim": date(2026, 12, 2),
                                        "notas": "Carta Verde emitida por Divina Seguros para Renault Mégane (AA-01-BB)."
                                    }
                                return None
                            def all(self):
                                return []
                        return MockMappings()
                    def fetchall(self):
                        if "FROM veiculo" in query_str:
                            from datetime import date
                            import uuid
                            return [
                                ("Sedan 2.0 TDI", "AA-01-BB", "carro", 170000, date(2026, 11, 15), 11, 2018, uuid.uuid4())
                            ]
                        return []
                    def fetchone(self):
                        return None
                return MockResult()
        yield MockSession()

    app_instance.dependency_overrides[get_session] = override_get_session
    return app_instance


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_healthcheck(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "app": "hub"}


@pytest.mark.asyncio
async def test_telemetry_endpoint(client):
    resp = await client.get("/api/telemetry")
    assert resp.status_code == 200
    dados = resp.json()
    assert "cpu_percent" in dados
    assert "ram_percent" in dados


@pytest.mark.asyncio
async def test_get_dashboard_hub(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "AVA" in resp.text
    assert "ORBITAL NEXUS" in resp.text


@pytest.mark.asyncio
async def test_chat_ai_endpoint(client):
    resp = await client.post("/api/chat", json={"query": "Qual é a próxima consulta do Junior?"})
    assert resp.status_code == 200
    dados = resp.json()
    assert "response" in dados
    assert len(dados["response"]) > 5


@pytest.mark.asyncio
async def test_chat_ai_despesas_eletricidade(client):
    resp = await client.post("/api/chat", json={"query": "quanto gastei em eletricidade?"})
    assert resp.status_code == 200
    dados = resp.json()
    assert "response" in dados
    assert len(dados["response"]) > 5


@pytest.mark.asyncio
async def test_chat_ai_agenda_query(client):
    resp = await client.post("/api/chat", json={"query": "o que tenho na agenda para hoje?"})
    assert resp.status_code == 200
    dados = resp.json()
    assert "response" in dados
    assert len(dados["response"]) > 5


@pytest.mark.asyncio
async def test_chat_ai_booking_command(client):
    resp = await client.post("/api/chat", json={
        "query": "marca consulta de pediatria para o Junior no dia 15 de setembro às 10:30 na CUF com a Dra. Sofia"
    })
    assert resp.status_code == 200
    dados = resp.json()
    assert "response" in dados
    assert "Marquei a consulta de **Pediatria** para o **Junior**" in dados["response"]
    assert "CUF" in dados["response"]
    assert "actions" in dados


@pytest.mark.asyncio
async def test_chat_ai_multi_turn_and_insurance(client):
    # Turno 1: Perguntar pelo seguro do Mégane
    resp1 = await client.post("/api/chat", json={
        "query": "qual é o seguro do sedan?",
        "session_id": "test_multi_turn",
    })
    assert resp1.status_code == 200
    dados1 = resp1.json()
    assert "Divina Seguros" in dados1["response"]
    assert len(dados1.get("actions", [])) >= 2  # Botão 24h e Vidros

    # Turno 2: Pergunta de seguimento com herança de viatura
    resp2 = await client.post("/api/chat", json={
        "query": "quantos km tem ele?",
        "session_id": "test_multi_turn",
    })
    assert resp2.status_code == 200
    dados2 = resp2.json()
    assert "Sedan 2.0 TDI" in dados2["response"]


@pytest.mark.asyncio
async def test_base_template_has_stark_hud_assets(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "stark_hud.css" in resp.text
    assert "STARK HUD" in resp.text or "ORBITAL NEXUS" in resp.text


@pytest.mark.asyncio
async def test_3d_engine_script_linked(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "nexus_orb_3d.js" in resp.text


@pytest.mark.asyncio
async def test_stark_hud_layout_elements(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "hud-panel" in resp.text
    assert "wealthGradStark" in resp.text or "liquid-wealth-wave" in resp.text
    assert "soundwave-canvas" in resp.text
    assert "btn-mic" in resp.text


@pytest.mark.asyncio
async def test_hud_drawer_script_and_markup(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "hud_drawer.js" in resp.text
    assert "hud-drawer-panel" in resp.text


@pytest.mark.asyncio
async def test_tts_api_endpoint(client):
    resp = await client.get("/api/tts?text=teste")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert len(resp.content) > 100


@pytest.mark.asyncio
async def test_cockpit_optimized_layout_elements(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    # Left Wing
    assert "Nodes Telemetry" in resp.text
    assert "NODE 01: PC" in resp.text
    assert "NODE 02: AVA HOST" in resp.text
    assert "Agenda Familiar" in resp.text
    assert "+ Evento" in resp.text
    assert "Próximos Compromissos" in resp.text

    # Right Wing
    assert "Liquid Wealth Wave" in resp.text
    assert "Family Health Status" in resp.text
    assert "Frota & Garagem" in resp.text
    assert "Garagem (:8082)" in resp.text
