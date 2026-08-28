from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from saude.extracao.sincronizador_gcal import (
    normalizar_especialidade,
    extrair_local_clinica,
    sincronizar_google_calendar_saude,
)

ICAL_EXEMPLO = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:Trofa Saúde - Consulta Psiquiatria
LOCATION:Alfena
DTSTART:20260831T140000Z
UID:test-123
END:VEVENT
BEGIN:VEVENT
SUMMARY:Trofa Saúde - Consulta Psiquiatria Da Infância/pedopsiquiatria
LOCATION:Boa Nova
DTSTART:20261014T103000Z
UID:test-456
END:VEVENT
END:VCALENDAR"""


def test_normalizacao_helpers():
    assert normalizar_especialidade("Trofa Saúde - Consulta Psiquiatria") == "Psiquiatria"
    assert "Pedopsiquiatria" in normalizar_especialidade("Trofa Saúde - Consulta Psiquiatria Da Infância/pedopsiquiatria") or "Psiquiatria" in normalizar_especialidade("Trofa Saúde - Consulta Psiquiatria Da Infância/pedopsiquiatria")
    assert normalizar_especialidade("Consulta de Medicina Dentária") == "Medicina Dentária"
    
    assert "Alfena" in extrair_local_clinica("Trofa Saúde - Consulta Psiquiatria", "Alfena")
    assert "Boa Nova" in extrair_local_clinica("Trofa Saúde - Consulta", "Boa Nova")


@pytest.mark.asyncio
async def test_sincronizar_google_calendar_saude_mock():
    session = AsyncMock()

    # Mock perfis
    perfil_alex = MagicMock()
    perfil_alex.id = "p-alex"
    perfil_alex.titular = MagicMock(nome="aa-stop-run")

    perfil_charlie = MagicMock()
    perfil_charlie.id = "p-charlie"
    perfil_charlie.titular = MagicMock(nome="Junior")

    res_perfis = MagicMock()
    res_perfis.scalars.return_value.all.return_value = [perfil_alex, perfil_charlie]

    res_cons = MagicMock()
    res_cons.all.return_value = []

    session.execute.side_effect = [res_perfis, res_cons]

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ICAL_EXEMPLO
        mock_get.return_value = mock_resp

        total = await sincronizar_google_calendar_saude(session, "http://fake-url.ics")
        assert total == 2
        assert session.add.call_count == 2
