import time
import logging
from datetime import datetime, date
import httpx

logger = logging.getLogger("hub.weather")

# Coordenadas: Área Metropolitana do Porto / Gondomar
LATITUDE = 41.15
LONGITUDE = -8.61
TIMEZONE = "Europe/Lisbon"

# Cache em memória
_cache_weather: dict | None = None
_cache_timestamp: float = 0.0
CACHE_TTL_SECONDS = 900.0  # 15 minutos


WMO_CODES = {
    0: ("Céu limpo", "☀️"),
    1: ("Predominantemente limpo", "🌤️"),
    2: ("Parcialmente nublado", "⛅"),
    3: ("Encoberto / Nublado", "☁️"),
    45: ("Nevoeiro", "🌫️"),
    48: ("Nevoeiro com geada", "🌫️"),
    51: ("Chuvisco ligeiro", "🌦️"),
    53: ("Chuvisco moderado", "🌦️"),
    55: ("Chuvisco denso", "🌧️"),
    56: ("Chuvisco gelado", "🌧️"),
    57: ("Chuvisco gelado denso", "🌧️"),
    61: ("Chuva fraca", "🌧️"),
    63: ("Chuva moderada", "🌧️"),
    65: ("Chuva forte", "🌧️"),
    66: ("Chuva gelada", "🌧️"),
    67: ("Chuva gelada forte", "🌧️"),
    71: ("Queda de neve fraca", "🌨️"),
    73: ("Queda de neve moderada", "🌨️"),
    75: ("Queda de neve intensa", "🌨️"),
    77: ("Granizo miúdo", "🌨️"),
    80: ("Aguaceiros fracos", "🌧️"),
    81: ("Aguaceiros moderados", "🌧️"),
    82: ("Aguaceiros violentos", "⛈️"),
    85: ("Aguaceiros de neve", "🌨️"),
    86: ("Aguaceiros de neve fortes", "🌨️"),
    95: ("Trovoada", "⛈️"),
    96: ("Trovoada com granizo leve", "⛈️"),
    99: ("Trovoada com granizo forte", "⛈️"),
}

DIAS_SEMANA_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
DIAS_SEMANA_COMPLETO_PT = [
    "Segunda-feira", "Terça-feira", "Quarta-feira",
    "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"
]


def _get_wmo_info(code: int) -> tuple[str, str]:
    return WMO_CODES.get(code, ("Tempo variável", "🌤️"))


def _obter_nivel_uv(uv: float) -> str:
    if uv < 3:
        return "Baixo"
    elif uv < 6:
        return "Moderado"
    elif uv < 8:
        return "Alto"
    elif uv < 11:
        return "Muito Alto"
    return "Extremo"


def get_fallback_weather() -> dict:
    return {
        "temperatura": 18.0,
        "sensacao": 17.5,
        "humidade": 75,
        "vento_kmh": 12.0,
        "descricao": "Parcialmente nublado",
        "icone": "⛅",
        "temp_min": 15.0,
        "temp_max": 22.0,
        "prob_chuva": 15,
        "precipitacao_mm": 0.0,
        "uv_index": 5.0,
        "uv_nivel": "Moderado",
        "localidade": "Porto / Gondomar",
        "hora_atualizacao": datetime.now().strftime("%H:%M"),
        "previsao_dias": [
            {
                "data": "Amanhã",
                "dia_curto": "Amanhã",
                "temp_min": 16.0,
                "temp_max": 23.0,
                "prob_chuva": 10,
                "icone": "🌤️",
                "descricao": "Predominantemente limpo",
            },
            {
                "data": "Depois",
                "dia_curto": "Sáb",
                "temp_min": 15.0,
                "temp_max": 24.0,
                "prob_chuva": 5,
                "icone": "☀️",
                "descricao": "Céu limpo",
            },
            {
                "data": "Domingo",
                "dia_curto": "Dom",
                "temp_min": 16.0,
                "temp_max": 22.0,
                "prob_chuva": 20,
                "icone": "⛅",
                "descricao": "Parcialmente nublado",
            },
        ],
    }


async def obter_dados_meteorologicos() -> dict:
    """Obtém dados meteorológicos em tempo real da Open-Meteo para a região do Porto."""
    global _cache_weather, _cache_timestamp

    now = time.time()
    if _cache_weather and (now - _cache_timestamp) < CACHE_TTL_SECONDS:
        return _cache_weather

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max"
        f"&timezone={TIMEZONE}"
    )

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(url, headers={"User-Agent": "AVA-Stark-HUD/3.0"})
            if resp.status_code != 200:
                logger.warning("Falha ao obter meteorologia Open-Meteo HTTP %s", resp.status_code)
                return _cache_weather or get_fallback_weather()

            data = resp.json()
            curr = data.get("current", {})
            daily = data.get("daily", {})

            wmo_code = curr.get("weather_code", 0)
            desc, icone = _get_wmo_info(wmo_code)

            temp = round(float(curr.get("temperature_2m", 18.0)), 1)
            sensacao = round(float(curr.get("apparent_temperature", temp)), 1)
            humidade = int(curr.get("relative_humidity_2m", 70))
            vento = round(float(curr.get("wind_speed_10m", 10.0)), 1)
            precip = round(float(curr.get("precipitation", 0.0)), 1)

            # Previsão diária (hoje + 3 dias seguintes)
            daily_times = daily.get("time", [])
            daily_codes = daily.get("weather_code", [])
            daily_max = daily.get("temperature_2m_max", [])
            daily_min = daily.get("temperature_2m_min", [])
            daily_prob = daily.get("precipitation_probability_max", [])
            daily_uv = daily.get("uv_index_max", [])

            temp_min_hoje = round(float(daily_min[0]), 1) if daily_min else temp - 3
            temp_max_hoje = round(float(daily_max[0]), 1) if daily_max else temp + 3
            prob_hoje = int(daily_prob[0]) if daily_prob else (100 if precip > 0 else 10)
            uv_hoje = round(float(daily_uv[0]), 1) if daily_uv else 5.0

            previsao_dias = []
            for i in range(1, min(4, len(daily_times))):
                dt_str = daily_times[i]
                try:
                    dt_obj = date.fromisoformat(dt_str)
                    dia_curto = DIAS_SEMANA_PT[dt_obj.weekday()]
                except Exception:
                    dia_curto = f"+{i}d"

                code_i = daily_codes[i] if i < len(daily_codes) else 0
                desc_i, icone_i = _get_wmo_info(code_i)

                previsao_dias.append({
                    "data": dt_str,
                    "dia_curto": dia_curto,
                    "temp_min": round(float(daily_min[i]), 1) if i < len(daily_min) else temp,
                    "temp_max": round(float(daily_max[i]), 1) if i < len(daily_max) else temp + 4,
                    "prob_chuva": int(daily_prob[i]) if i < len(daily_prob) else 10,
                    "icone": icone_i,
                    "descricao": desc_i,
                })

            res = {
                "temperatura": temp,
                "sensacao": sensacao,
                "humidade": humidade,
                "vento_kmh": vento,
                "descricao": desc,
                "icone": icone,
                "temp_min": temp_min_hoje,
                "temp_max": temp_max_hoje,
                "prob_chuva": prob_hoje,
                "precipitacao_mm": precip,
                "uv_index": uv_hoje,
                "uv_nivel": _obter_nivel_uv(uv_hoje),
                "localidade": "Porto / Gondomar",
                "hora_atualizacao": datetime.now().strftime("%H:%M"),
                "previsao_dias": previsao_dias,
            }

            _cache_weather = res
            _cache_timestamp = now
            return res

    except Exception as e:
        logger.warning("Erro ao consultar Open-Meteo: %s", e)
        return _cache_weather or get_fallback_weather()
