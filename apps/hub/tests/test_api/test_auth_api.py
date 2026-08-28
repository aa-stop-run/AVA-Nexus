import pytest
from httpx import ASGITransport, AsyncClient
from hub.main import create_app
from hub.services.auth_service import verificar_pin, criar_token_sessao, validar_token_sessao


def test_auth_service_pin_verification():
    # 1234 -> aa-stop-run
    user_alex = verificar_pin("1234")
    assert user_alex is not None
    assert user_alex["id"] == "alex"
    assert user_alex["nome"] == "aa-stop-run"

    # 5678 -> Member
    user_sam = verificar_pin("5678")
    assert user_sam is not None
    assert user_sam["id"] == "sam"
    assert user_sam["nome"] == "Member"

    # PINs inválidos
    assert verificar_pin("0000") is None
    assert verificar_pin("9999") is None
    assert verificar_pin("") is None


def test_auth_service_token_lifecycle():
    token_alex = criar_token_sessao(user_id="alex", duracao_dias=30)
    user = validar_token_sessao(token_alex)
    assert user is not None
    assert user["nome"] == "aa-stop-run"

    token_sam = criar_token_sessao(user_id="sam", duracao_dias=30)
    user_s = validar_token_sessao(token_sam)
    assert user_s is not None
    assert user_s["nome"] == "Member"

    assert validar_token_sessao("token_falso") is None
    assert validar_token_sessao(None) is None


@pytest.mark.asyncio
async def test_api_login_pin_incorreto():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/auth/pin", json={"pin": "9999"})
        assert resp.status_code == 401
        assert "ava_session_token" not in resp.cookies


@pytest.mark.asyncio
async def test_api_login_pin_correto_e_logout():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Login com 1234 (aa-stop-run)
        resp = await client.post("/api/auth/pin", json={"pin": "1234"})
        assert resp.status_code == 200
        dados = resp.json()
        assert dados["authenticated"] is True
        assert dados["user"]["nome"] == "aa-stop-run"
        assert "ava_session_token" in resp.cookies

        # 2. Verificar estado de autenticado
        resp_status = await client.get("/api/auth/status")
        assert resp_status.status_code == 200
        assert resp_status.json()["authenticated"] is True
        assert resp_status.json()["user"]["nome"] == "aa-stop-run"

        # 3. Login com 5678 (Member)
        resp_sam = await client.post("/api/auth/pin", json={"pin": "5678"})
        assert resp_sam.status_code == 200
        dados_s = resp_sam.json()
        assert dados_s["user"]["nome"] == "Member"

        # 4. Logout
        resp_logout = await client.post("/api/auth/logout")
        assert resp_logout.status_code == 200
        assert resp_logout.json()["authenticated"] is False


@pytest.mark.asyncio
async def test_pwa_manifest_and_sw():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp_manifest = await client.get("/manifest.json")
        assert resp_manifest.status_code == 200
        assert "AVA" in resp_manifest.text
        assert "standalone" in resp_manifest.text

        resp_sw = await client.get("/sw.js")
        assert resp_sw.status_code == 200
        assert "ava-cache-v2" in resp_sw.text
        # '/' NUNCA deve estar em ASSETS_TO_CACHE (evita servir HTML obsoleto sem sessão)
        assets_block = resp_sw.text.split("ASSETS_TO_CACHE = [")[1].split("];")[0]
        assert "'/'" not in assets_block
        assert '"/"' not in assets_block
        assert "navigate" in resp_sw.text


@pytest.mark.asyncio
async def test_dashboard_cache_control_headers():
    from hub.db import get_session
    app = create_app()

    async def override_get_session():
        class MockSession:
            async def commit(self):
                pass
            async def execute(self, *args, **kwargs):
                class MockResult:
                    def scalar(self): return 0
                    def scalars(self):
                        class MockScalars:
                            def all(self): return []
                        return MockScalars()
                    def mappings(self):
                        class MockMappings:
                            def all(self): return []
                            def first(self): return None
                            def __iter__(self): return iter([])
                        return MockMappings()
                    def fetchall(self): return []
                    def fetchone(self): return None
                return MockResult()
        yield MockSession()

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Sem cookie: lockscreen presente e Cache-Control no-store para não guardar em cache de browser/SW
        resp_unauth = await client.get("/")
        assert resp_unauth.status_code == 200
        assert "no-store" in resp_unauth.headers.get("cache-control", "").lower()
        assert "pin-lockscreen-modal" in resp_unauth.text

        # 2. Login com PIN da Member (5678)
        resp_login = await client.post("/api/auth/pin", json={"pin": "5678"})
        assert resp_login.status_code == 200
        assert resp_login.json()["user"]["nome"] == "Member"

        # 3. Com cookie da Member: lockscreen escondido e utilizador Member renderizado
        resp_auth = await client.get("/")
        assert resp_auth.status_code == 200
        assert "no-store" in resp_auth.headers.get("cache-control", "").lower()
        assert 'id="pin-lockscreen-modal" class="hidden' in resp_auth.text
        assert "Member" in resp_auth.text

