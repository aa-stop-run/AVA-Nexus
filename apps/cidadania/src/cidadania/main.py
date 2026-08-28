import pathlib
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from cidadania.api.cidadania_api import router as cidadania_router
from cidadania.config import get_settings
from cidadania.db import make_engine, make_session_factory
from cidadania.models.base import Base
import cidadania.models.documento_identificacao
import cidadania.models.obrigacao_fiscal


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = make_engine(settings.database_url)

    # Cria as tabelas do domínio cidadania se não existirem
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.state.session_factory = make_session_factory(engine)
    async with app.state.session_factory() as session:
        from cidadania.repositories import cidadania_repo
        await cidadania_repo.garantir_dados_iniciais(session)

    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Cidadania, Documentos & Tax Deadlines — AVA", lifespan=lifespan)

    static_dir = pathlib.Path(__file__).resolve().parent / "static"
    if not static_dir.exists():
        static_dir = pathlib.Path("src/cidadania/static")
    if not static_dir.exists():
        static_dir = pathlib.Path("/app/src/cidadania/static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(cidadania_router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "app": "cidadania"}

    return app


app = create_app()
