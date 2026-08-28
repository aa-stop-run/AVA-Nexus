from fastapi import APIRouter
from hub.services.telemetry import obter_telemetria_sistema

router = APIRouter(prefix="/api", tags=["telemetria"])


@router.get("/telemetry")
async def get_telemetry():
    """Retorna métricas em tempo real de hardware."""
    return obter_telemetria_sistema()
