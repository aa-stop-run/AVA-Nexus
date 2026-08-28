import pytest
from hub.services.ai_briefing import gerar_daily_briefing
from hub.services.saude_metrics_service import processar_e_guardar_metricas


def test_gerar_daily_briefing_com_metricas_saude():
    # 1. Regista métricas de saúde do smartwatch
    processar_e_guardar_metricas({
        "titular": "aa-stop-run",
        "data_referencia": "2026-08-27",
        "sono": {"minutos_total": 450, "score": 86},
        "atividade": {"passos": 6500},
        "cardiovascular": {"bpm_repouso": 56},
    })

    dados = {
        "agenda_eventos_hoje": [{"hora": "10:00", "titulo": "Reunião de Projeto"}],
        "agenda_total_hoje": 1,
    }

    briefing = gerar_daily_briefing(dados, user_nome="aa-stop-run")
    assert "saudacao" in briefing
    assert len(briefing["pontos"]) >= 3
    # Verifica que algum ponto fala do sono ou recuperação
    texto_total = " ".join(briefing["pontos"])
    assert "sono" in texto_total or "recuperação" in texto_total or "7h30m" in texto_total


def test_gerar_daily_briefing_sem_metricas_saude():
    dados = {
        "agenda_eventos_hoje": [],
        "agenda_total_hoje": 0,
        "agenda_eventos": [],
    }
    briefing = gerar_daily_briefing(dados, user_nome="aa-stop-run", incluir_saude=False)
    assert len(briefing["pontos"]) >= 2
