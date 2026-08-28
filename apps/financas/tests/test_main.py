import pytest
from httpx import ASGITransport, AsyncClient

from ava.main import create_app




@pytest.mark.asyncio
async def test_health_returns_ok():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_lifespan_sets_up_session_factory():
    app = create_app()
    async with app.router.lifespan_context(app):
        assert app.state.session_factory is not None
