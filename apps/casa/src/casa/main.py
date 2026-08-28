import pathlib
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from casa.api.casa_api import router as casa_router
from casa.config import get_settings
from casa.db import make_engine, make_session_factory
from casa.models.base import Base
import casa.models.equipamento
import casa.models.manutencao


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = make_engine(settings.database_url)

    # Cria as tabelas do domínio casa se não existirem
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.state.session_factory = make_session_factory(engine)
    async with app.state.session_factory() as session:
        from casa.repositories import casa_repo
        await casa_repo.garantir_dados_iniciais(session)

    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Casa, Warranties & Manutenção — AVA", lifespan=lifespan)

    static_dir = pathlib.Path(__file__).resolve().parent / "static"
    if not static_dir.exists():
        static_dir = pathlib.Path("src/casa/static")
    if not static_dir.exists():
        static_dir = pathlib.Path("/app/src/casa/static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(casa_router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "app": "casa"}

    return app


app = create_app()
