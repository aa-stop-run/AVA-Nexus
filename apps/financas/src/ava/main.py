import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ava.alerts.scheduler import iniciar_scheduler
from ava.api.alertas import router as alertas_router
from ava.api.ativos import router as ativos_router
from ava.api.configuracoes import router as configuracoes_router
from ava.api.contratos import router as contratos_router
from ava.api.fila import router as fila_router
from ava.api.home import router as home_router
from ava.api.importacao import router as importacao_router
from ava.api.metas import router as metas_router
from ava.api.movimentos import router as movimentos_router
from ava.api.otimizador import router as otimizador_router
from ava.api.patrimonio import router as patrimonio_router
from ava.api.reconciliacao import router as reconciliacao_router
from ava.api.simulador import router as simulador_router
from ava.api.tesouraria import router as tesouraria_router
from ava.config import get_settings
from ava.db import make_engine, make_session_factory
from ava.integrations.paperless import PaperlessClient

logger = logging.getLogger("ava.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = make_engine(settings.database_url)
    app.state.session_factory = make_session_factory(engine)
    app.state.paperless_client = PaperlessClient(
        base_url=settings.paperless_url, token=settings.paperless_token
    )
    scheduler = iniciar_scheduler(app.state.session_factory, app.state.paperless_client)

    yield

    scheduler.shutdown()
    await app.state.paperless_client.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Assistente de Vida Pessoal", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory="src/ava/static"), name="static")
    app.include_router(fila_router)
    app.include_router(home_router)
    app.include_router(patrimonio_router)
    app.include_router(ativos_router)
    app.include_router(contratos_router)
    app.include_router(movimentos_router)
    app.include_router(alertas_router)
    app.include_router(configuracoes_router)
    app.include_router(importacao_router)
    app.include_router(reconciliacao_router)
    app.include_router(simulador_router)
    app.include_router(metas_router)
    app.include_router(otimizador_router)
    app.include_router(tesouraria_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
