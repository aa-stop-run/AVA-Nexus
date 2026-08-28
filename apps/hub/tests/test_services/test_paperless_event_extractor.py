import pytest
from datetime import datetime, timezone
from hub.services.paperless_event_extractor import _extrair_data_hora_bilhete, extrair_e_sincronizar_paperless


def test_extrair_data_hora_bilhete():
    texto_bilhete = """
    This is your ticket Present this entire page at the event
    sexta-feira, 4 de setembro de 2026, 14:30 Doors open at 13:45
    Friday Ticket PL3 Issued to Andre
    """
    res = _extrair_data_hora_bilhete(texto_bilhete)
    assert res is not None
    dt, fmt = res
    assert dt.year == 2026
    assert dt.month == 9
    assert dt.day == 4
    assert dt.hour == 14
    assert dt.minute == 30
    assert "04/09/2026 14:30" in fmt


@pytest.mark.asyncio
async def test_extrair_e_sincronizar_paperless_mock(monkeypatch):
    class MockResponse:
        status_code = 200
        def json(self):
            return {
                "count": 1,
                "results": [
                    {
                        "id": 76,
                        "title": "Tickets for: Friday Ticket",
                        "content": "This is your ticket sexta-feira, 4 de setembro de 2026, 14:30 Friday Ticket"
                    }
                ]
            }

    import httpx
    async def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    class MockResult:
        def scalar(self):
            return None  # Não existe ainda

    queries = []
    class MockSession:
        async def execute(self, stmt, params=None):
            queries.append((str(stmt), params))
            return MockResult()
        async def commit(self):
            pass

    session = MockSession()
    relatorio = await extrair_e_sincronizar_paperless(session, "http://mock-paperless", "mock-token")
    assert relatorio["documentos_analisados"] == 1
    assert relatorio["eventos_criados"] == 1
    assert any("INSERT INTO evento_calendario" in q[0] for q in queries)
