import pytest
from hub.services.telemetry import obter_telemetria_sistema
from hub.services.homelab import listar_servicos_homelab
from hub.services.ai_briefing import gerar_daily_briefing


def test_obter_telemetria_sistema():
    stats = obter_telemetria_sistema()
    assert "cpu_percent" in stats
    assert "ram_percent" in stats
    assert "disk_percent" in stats
    assert "uptime" in stats


def test_listar_servicos_homelab():
    servicos = listar_servicos_homelab()
    assert len(servicos) >= 8
    nomes = [s["nome"] for s in servicos]
    assert "LiteLLM" in nomes
    assert "Nextcloud" in nomes
    assert "Immich" in nomes
    assert "Paperless-ngx" in nomes


def test_gerar_daily_briefing():
    dados = {
        "patrimonio_total": 150000.0,
        "despesas_mes": 2500.0,
        "total_faturas_pendentes": 1,
        "consultas_futuras": [],
        "veiculos": [{"nome": "Sedan 2.0 TDI"}, {"nome": "City Hatchback 1.2"}],
    }
    briefing = gerar_daily_briefing(dados)
    assert "saudacao" in briefing
    assert len(briefing["pontos"]) >= 2
    assert "texto_fala" in briefing


def test_calcular_coordenadas_wave():
    from hub.services.consolidator import _calcular_coordenadas_wave
    historico = [
        {"mes_id": "2026-03", "mes_curto": "Mar", "valor": 238383.17},
        {"mes_id": "2026-04", "mes_curto": "Abr", "valor": 242282.59},
        {"mes_id": "2026-05", "mes_curto": "Mai", "valor": 242469.27},
        {"mes_id": "2026-06", "mes_curto": "Jun", "valor": 239836.38},
        {"mes_id": "2026-07", "mes_curto": "Jul", "valor": 239641.55},
        {"mes_id": "2026-08", "mes_curto": "Ago", "valor": 239314.11},
    ]
    path_d, area_d, pontos = _calcular_coordenadas_wave(historico, largura=240, altura=70)
    assert path_d.startswith("M")
    assert "C" in path_d
    assert area_d.endswith("Z")
    assert len(pontos) == 6
    assert pontos[0]["mes"] == "Mar"
    assert pontos[-1]["mes"] == "Ago"
    assert 0 <= pontos[0]["x"] <= 240
    assert 0 <= pontos[0]["y"] <= 70


@pytest.mark.asyncio
async def test_obter_dados_meteorologicos():
    from hub.services.weather_service import obter_dados_meteorologicos, get_fallback_weather
    data = await obter_dados_meteorologicos()
    assert "temperatura" in data
    assert "descricao" in data
    assert "icone" in data
    assert "previsao_dias" in data
    assert len(data["previsao_dias"]) >= 1

