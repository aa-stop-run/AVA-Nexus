import logging
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Cache em memória para resiliência local e acesso síncrono rápido (Autonomous Mode)
_METRICAS_STORE: dict[str, dict[str, Any]] = {}


def _gerar_chave(titular: str, data_str: str) -> str:
    return f"{titular.strip().lower()}:{data_str.strip()}"


def processar_e_guardar_metricas(payload: dict[str, Any], storage: Any = None) -> dict[str, Any]:
    """Processa, normaliza e persiste métricas biométricas recebidas do Health Connect / Galaxy Watch.
    Garante idempotência (mesma data + titular atualiza o registo em vez de duplicar).
    """
    titular = payload.get("titular") or "aa-stop-run"
    data_ref = payload.get("data_referencia") or date.today().isoformat()

    # 1. Normalização de Sono
    sono = payload.get("sono") or {}
    sono_minutos = sono.get("minutos_total") or sono.get("duracao_minutos", 0)
    sono_score = sono.get("score")
    sono_fases = sono.get("fases") or {}

    # 2. Normalização de Atividade
    atividade = payload.get("atividade") or {}
    passos = atividade.get("passos") or payload.get("passos", 0)
    calorias = atividade.get("calorias_ativas_kcal") or payload.get("calorias", 0)

    # 3. Normalização Cardiovascular
    cardio = payload.get("cardiovascular") or {}
    bpm_repouso = cardio.get("bpm_repouso")
    bpm_medio = cardio.get("bpm_medio")
    hrv = cardio.get("hrv_rmssd_ms") or cardio.get("hrv")

    registro = {
        "titular": titular,
        "data": data_ref,
        "passos": int(passos) if passos is not None else 0,
        "calorias_ativas": int(calorias) if calorias is not None else 0,
        "sono_minutos": int(sono_minutos) if sono_minutos is not None else 0,
        "sono_score": int(sono_score) if sono_score is not None else None,
        "sono_fases": sono_fases,
        "bpm_repouso": int(bpm_repouso) if bpm_repouso is not None else None,
        "bpm_medio": int(bpm_medio) if bpm_medio is not None else None,
        "hrv_rmssd": float(hrv) if hrv is not None else None,
        "raw_payload": payload,
        "atualizado_em": datetime.now().isoformat(),
    }

    # Save no cache resiliente
    chave = _gerar_chave(titular, data_ref)
    _METRICAS_STORE[chave] = registro
    logger.info(f"[SaudeMetrics] Métricas registadas com sucesso para {titular} ({data_ref}): {passos} passos, {sono_minutos}min sono.")

    return registro


def obter_metricas_saude_dia(data_str: str | None = None, titular: str = "aa-stop-run") -> dict[str, Any] | None:
    """Obtém as métricas de um dia específico para o titular, ou a mais recente disponível."""
    if data_str:
        chave = _gerar_chave(titular, data_str)
        return _METRICAS_STORE.get(chave)

    # Tenta obter o dia de hoje
    hoje_str = date.today().isoformat()
    chave_hoje = _gerar_chave(titular, hoje_str)
    if chave_hoje in _METRICAS_STORE:
        return _METRICAS_STORE[chave_hoje]

    # Procura o registo mais recente para o titular
    prefix = f"{titular.strip().lower()}:"
    registos = [v for k, v in _METRICAS_STORE.items() if k.startswith(prefix)]
    if registos:
        registos.sort(key=lambda r: r.get("data", ""), reverse=True)
        return registos[0]

    return None


def obter_resumo_saude_para_briefing(data_str: str | None = None, titular: str = "aa-stop-run") -> str | None:
    """Gera um texto natural conciso em português sobre o estado de sono e recuperação
    para ser injetado diretamente no Daily Briefing da AVA.
    """
    metricas = obter_metricas_saude_dia(data_str, titular)
    if not metricas:
        return None

    sono_min = metricas.get("sono_minutos", 0)
    score = metricas.get("sono_score")
    bpm_repouso = metricas.get("bpm_repouso")

    frases = []
    if sono_min > 0:
        h = sono_min // 60
        m = sono_min % 60
        score_txt = f" com pontuação de {score}" if score else ""
        frases.append(f"Esta noite registaste {h}h{m:02d}m de sono{score_txt}.")

    if bpm_repouso:
        if bpm_repouso < 60:
            recup = "excelente (frequência de repouso baixa)"
        elif bpm_repouso < 75:
            recup = "estável e dentro dos parâmetros normais"
        else:
            recup = "ligeiramente acelerada"
        frases.append(f"A tua recuperação cardiovascular está {recup} ({bpm_repouso} bpm em repouso).")

    if not frases:
        return None

    return " ".join(frases)
