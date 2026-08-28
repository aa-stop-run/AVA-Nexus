import re
import edge_tts
from fastapi import APIRouter, Response, Query
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/tts", tags=["tts"])

# Neural JARVIS Voice Profiles
VOICE_JARVIS_PT = "pt-PT-DuarteNeural"  # Official Microsoft European Portuguese Male Neural Voice
VOICE_JARVIS_EN = "en-GB-RyanNeural"    # Official Microsoft British English Male Neural Voice (Paul Bettany style)


def limpar_texto_para_tts(texto: str) -> str:
    """Remove símbolos markdown (*, _, `, #) e normaliza moedas para uma leitura de voz fluida."""
    if not texto:
        return ""
    # Remove marcações markdown
    t = re.sub(r"\*{1,2}", "", texto)
    t = re.sub(r"_{1,2}", "", t)
    t = re.sub(r"`{1,3}", "", t)
    t = re.sub(r"#+\s*", "", t)
    # Converte moedas: € 83.39 ou 83.39 € -> 83.39 euros
    t = re.sub(r"€\s*(\d+(?:[.,]\d+)?)", r"\1 euros", t)
    t = re.sub(r"(\d+(?:[.,]\d+)?)\s*€", r"\1 euros", t)
    # Remove emojis
    t = re.sub(r"[\U00010000-\U0010ffff]", "", t)
    return re.sub(r"\s+", " ", t).strip()


@router.get("")
async def generate_speech(text: str = Query(..., min_length=1), lang: str = Query("pt")):
    """Gera áudio em streaming MP3 com voz neural masculina estilo JARVIS (pt-PT-DuarteNeural)."""
    try:
        texto_limpo = limpar_texto_para_tts(text)
        if not texto_limpo:
            texto_limpo = text

        voice = VOICE_JARVIS_PT if lang.startswith("pt") else VOICE_JARVIS_EN
        # Tom ligeiramente barítono (-4Hz) e ritmo firme (+0%) para atmosfera de inteligência artificial
        communicate = edge_tts.Communicate(texto_limpo, voice, rate="+0%", pitch="-4Hz")
        audio_bytes = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_bytes.extend(chunk["data"])

        return Response(content=bytes(audio_bytes), media_type="audio/mpeg")
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
