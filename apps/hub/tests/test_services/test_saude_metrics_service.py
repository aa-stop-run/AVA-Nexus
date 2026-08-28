import pytest
from hub.services.saude_metrics_service import (
    processar_e_guardar_metricas,
    obter_metricas_saude_dia,
    obter_resumo_saude_para_briefing,
)


def test_processar_e_guardar_metricas_valido():
    payload = {
        "titular": "aa-stop-run",
        "data_referencia": "2026-08-27",
        "sono": {
            "minutos_total": 450,
            "score": 84,
            "fases": {
                "profundo_minutos": 90,
                "rem_minutos": 95,
                "leve_minutos": 240,
                "acordado_minutos": 25,
            },
        },
        "atividade": {
            "passos": 7500,
            "calorias_ativas_kcal": 380,
        },
        "cardiovascular": {
            "bpm_repouso": 58,
            "bpm_medio": 72,
            "hrv_rmssd_ms": 45.0,
        },
    }

    resumo = processar_e_guardar_metricas(payload)
    assert resumo["titular"] == "aa-stop-run"
    assert resumo["data"] == "2026-08-27"
    assert resumo["passos"] == 7500
    assert resumo["sono_minutos"] == 450
    assert resumo["sono_score"] == 84
    assert resumo["bpm_repouso"] == 58

    # Verificar recuperação subsequente
    salvo = obter_metricas_saude_dia("2026-08-27", "aa-stop-run")
    assert salvo is not None
    assert salvo["passos"] == 7500


def test_obter_resumo_saude_para_briefing():
    payload = {
        "titular": "aa-stop-run",
        "data_referencia": "2026-08-27",
        "sono": {
            "minutos_total": 465,  # 7h45m
            "score": 88,
        },
        "atividade": {
            "passos": 8300,
        },
        "cardiovascular": {
            "bpm_repouso": 54,
        },
    }
    processar_e_guardar_metricas(payload)

    texto = obter_resumo_saude_para_briefing("2026-08-27", "aa-stop-run")
    assert texto is not None
    assert "7h45m" in texto
    assert "88" in texto or "sono" in texto
