import os
import pathlib
from typing import Any
from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import FileResponse
from hub.services.saude_metrics_service import processar_e_guardar_metricas

router = APIRouter(tags=["Saúde Sync & Mobile"])

DEFAULT_DEVICE_TOKEN = os.getenv("AVA_DEVICE_TOKEN", "ava-mobile-device-token-2026")


@router.post("/api/saude/sync/health-connect")
async def sync_health_connect(
    payload: dict[str, Any],
    x_ava_device_token: str | None = Header(None, alias="X-AVA-Device-Token"),
):
    """Endpoint receptor de telemetria biométrica do Google Health Connect / Galaxy Watch 8."""
    if not x_ava_device_token or x_ava_device_token != DEFAULT_DEVICE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de dispositivo inválido ou ausente. Acesso restrito à app AVA Mobile.",
        )

    try:
        registro = processar_e_guardar_metricas(payload)
        return {
            "status": "ok",
            "mensagem": "Métricas de saúde sincronizadas com sucesso",
            "titular": registro["titular"],
            "data": registro["data"],
            "passos": registro["passos"],
            "sono_minutos": registro["sono_minutos"],
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao processar métricas de saúde: {str(e)}",
        )


@router.get("/downloads/ava-mobile.apk")
async def download_ava_mobile_apk():
    """Permite descarregar o APK compilado da AVA Mobile diretamente no smartphone."""
    caminhos_possiveis = [
        pathlib.Path(__file__).resolve().parent.parent / "static" / "downloads" / "ava-mobile.apk",
        pathlib.Path("src/hub/static/downloads/ava-mobile.apk"),
        pathlib.Path("/app/src/hub/static/downloads/ava-mobile.apk"),
    ]

    for p in caminhos_possiveis:
        if p.exists():
            return FileResponse(
                path=str(p),
                media_type="application/vnd.android.package-archive",
                filename="ava-mobile.apk",
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="O ficheiro ava-mobile.apk ainda não está disponível para download.",
    )
