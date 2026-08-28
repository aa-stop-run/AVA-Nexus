import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from saude.api.dashboard import router as dashboard_router
from saude.api.perfis import router as perfis_router
from saude.api.documentos import router as documentos_router
from saude.api.medicamentos import router as medicamentos_router
from saude.config import get_settings
from saude.db import make_engine, make_session_factory
from saude.models.base import Base
import saude.models.titular
import saude.models.perfil
import saude.models.consulta
import saude.models.exame
import saude.models.medicamento
import saude.models.vacina
import saude.models.biomarcador
import saude.models.documento


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = make_engine(settings.database_url)
    
    # Cria as tabelas do domínio saude se não existirem
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    app.state.session_factory = make_session_factory(engine)
    async with app.state.session_factory() as session:
        from saude.repositories import saude_repo
        await saude_repo.garantir_titulares_e_perfis(session)

    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Saúde Familiar & Health Dossier — AVA", lifespan=lifespan)
    
    static_dir = pathlib.Path(__file__).resolve().parent / "static"
    if not static_dir.exists():
        static_dir = pathlib.Path("src/saude/static")
    if not static_dir.exists():
        static_dir = pathlib.Path("/app/src/saude/static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(dashboard_router)
    app.include_router(perfis_router)
    app.include_router(documentos_router)
    app.include_router(medicamentos_router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "app": "saude"}

    return app


app = create_app()
