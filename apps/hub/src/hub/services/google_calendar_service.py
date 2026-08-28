import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger("hub.google_calendar")

# Cache em memória: {url: {"timestamp": float, "events": list}}
_CACHE_ICAL: Dict[str, Dict[str, Any]] = {}
CACHE_TTL_SEGUNDOS = 600  # 10 minutos


def _parse_ical_datetime(val_str: str) -> tuple[str, str]:
    """
    Converte strings iCal como '20260418T100000Z' ou '20260513' em (YYYY-MM-DD, HH:MM).
    Considera fuso horário de Portugal (WET/WEST). No verão (Agosto/Setembro), UTC+1.
    """
    val_clean = val_str.strip()
    # Caso 1: Apenas data (ex: '20260513' ou 'VALUE=DATE:20260513')
    if ":" in val_clean:
        val_clean = val_clean.split(":")[-1].strip()

    if len(val_clean) == 8 and val_clean.isdigit():
        d_str = f"{val_clean[:4]}-{val_clean[4:6]}-{val_clean[6:8]}"
        return d_str, "00:00"

    # Caso 2: Data e Hora (ex: '20260418T100000Z' ou '20260418T110000')
    if "T" in val_clean:
        partes = val_clean.split("T")
        d_part = partes[0]
        t_part = partes[1].replace("Z", "")
        if len(d_part) == 8 and len(t_part) >= 4:
            d_str = f"{d_part[:4]}-{d_part[4:6]}-{d_part[6:8]}"
            h_int = int(t_part[:2])
            m_int = int(t_part[2:4])
            
            # Se for Z (UTC), converter para hora de Portugal
            if val_clean.endswith("Z"):
                try:
                    dt_utc = datetime(int(d_part[:4]), int(d_part[4:6]), int(d_part[6:8]), h_int, m_int, tzinfo=timezone.utc)
                    mes = dt_utc.month
                    offset_hours = 1 if (4 <= mes <= 10) else 0
                    dt_local = dt_utc + timedelta(hours=offset_hours)
                    return dt_local.strftime("%Y-%m-%d"), dt_local.strftime("%H:%M")
                except Exception:
                    pass

            return d_str, f"{h_int:02d}:{m_int:02d}"

    return val_clean[:10], "00:00"


def parse_ical_content(content: str) -> List[Dict[str, Any]]:
    """Faz o parse do formato VCALENDAR / VEVENT padrão RFC 5545."""
    eventos: List[Dict[str, Any]] = []
    
    # Normalizar quebras de linha com continuação RFC 5545 (linhas que começam com espaço/tab)
    content_unfolded = re.sub(r"\r?\n[ \t]", "", content)
    
    raw_events = content_unfolded.split("BEGIN:VEVENT")
    for block in raw_events[1:]:
        if "END:VEVENT" not in block:
            continue
        body = block.split("END:VEVENT")[0]
        
        props: Dict[str, str] = {}
        for line in body.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            k, v = line.split(":", 1)
            # Normalizar chaves com parâmetros (ex: DTSTART;VALUE=DATE)
            k_base = k.split(";")[0].upper()
            if k_base not in props:
                props[k_base] = v

        summary = props.get("SUMMARY", "Compromisso").replace(r"\,", ",").replace(r"\;", ";").replace(r"\n", " ").strip()
        location = props.get("LOCATION", "").replace(r"\,", ",").replace(r"\;", ";").replace(r"\n", " ").strip()
        uid = props.get("UID", "").strip() or f"gcal-{hash(summary)}"
        dtstart = props.get("DTSTART", "")

        if not dtstart:
            continue

        data_str, hora_str = _parse_ical_datetime(dtstart)

        eventos.append({
            "id": f"google-{uid}",
            "origem_id": uid,
            "titulo": summary,
            "subtitulo": location or "Google Calendar",
            "data": data_str,
            "hora": hora_str,
            "tipo": "google",
            "cor": "sky",
            "icone": "google",
            "local": location,
            "origem": "google",
            "editavel": True,
        })

    return eventos


async def obter_eventos_google_calendar(ical_url: str, force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Descarrega o feed iCal do Google Calendar e devolve a lista de eventos com cache em memória.
    """
    if not ical_url:
        return []

    agora = time.time()
    if not force_refresh and ical_url in _CACHE_ICAL:
        cached = _CACHE_ICAL[ical_url]
        if agora - cached["timestamp"] < CACHE_TTL_SEGUNDOS:
            return cached["events"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(ical_url, headers={"User-Agent": "AVA-Personal-Assistant/1.0"})
            if resp.status_code != 200:
                logger.warning("Falha ao obter iCal da Google: HTTP %s", resp.status_code)
                if ical_url in _CACHE_ICAL:
                    return _CACHE_ICAL[ical_url]["events"]
                return []

            content = resp.text
            eventos = parse_ical_content(content)
            _CACHE_ICAL[ical_url] = {
                "timestamp": agora,
                "events": eventos
            }
            logger.info("Google Calendar sincronizado com sucesso: %d eventos encontrados", len(eventos))
            return eventos
    except Exception as e:
        logger.error("Erro ao sincronizar com Google Calendar: %s", e)
        if ical_url in _CACHE_ICAL:
            return _CACHE_ICAL[ical_url]["events"]
        return []
