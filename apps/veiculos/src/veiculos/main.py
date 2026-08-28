import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from veiculos.api.garagem import router as garagem_router
from veiculos.api.veiculos import router as veiculos_router
from veiculos.config import get_settings
from veiculos.db import make_engine, make_session_factory
from veiculos.models.base import Base
import veiculos.models.veiculo
import veiculos.models.manutencao
import veiculos.models.abastecimento


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = make_engine(settings.database_url)
    
    # Cria as tabelas se ainda não existirem (para migrações automáticas sem dor de cabeça)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    app.state.session_factory = make_session_factory(engine)
    async with app.state.session_factory() as session:
        from veiculos.seed import semear_veiculos_iniciais
        await semear_veiculos_iniciais(session)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Garagem & Gestão de Veículos — AVA", lifespan=lifespan)
    
    static_dir = pathlib.Path(__file__).resolve().parent / "static"
    if not static_dir.exists():
        static_dir = pathlib.Path("src/veiculos/static")
    if not static_dir.exists():
        static_dir = pathlib.Path("/app/src/veiculos/static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(garagem_router)
    app.include_router(veiculos_router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "app": "veiculos"}

    return app


app = create_app()
