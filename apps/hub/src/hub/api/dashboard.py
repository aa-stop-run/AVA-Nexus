from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from hub.api.shared import templates
from hub.db import get_session
from hub.services.ai_briefing import gerar_daily_briefing
from hub.services.consolidator import recolher_dados_consolidados
from hub.services.auth_service import validar_token_sessao
from hub.services.homelab import listar_servicos_homelab
from hub.services.telemetry import obter_telemetria_sistema
from hub.services.weather_service import obter_dados_meteorologicos

router = APIRouter(tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    """Renderiza a página principal do AVA Cockpit com verificação de autenticação por PIN."""
    cookie_token = request.cookies.get("ava_session_token")
    utilizador = validar_token_sessao(cookie_token)
    autenticado = utilizador is not None
    user_nome = utilizador["nome"] if utilizador else "aa-stop-run"

    dados_consolidados = await recolher_dados_consolidados(session)
    meteo = await obter_dados_meteorologicos()
    briefing = gerar_daily_briefing(dados_consolidados, meteo=meteo, user_nome=user_nome)
    telemetria = obter_telemetria_sistema()
    servicos_homelab = listar_servicos_homelab()

    return templates.TemplateResponse(
        request,
        "hub.html",
        {
            "dados": dados_consolidados,
            "briefing": briefing,
            "telemetria": telemetria,
            "meteo": meteo,
            "servicos_homelab": servicos_homelab,
            "ano_atual": 2026,
            "autenticado": autenticado,
            "utilizador": utilizador,
        },
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
