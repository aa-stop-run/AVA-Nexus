import pathlib
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from hub.api.dashboard import router as dashboard_router
from hub.api.telemetry_api import router as telemetry_router
from hub.api.chat_ai import router as chat_router
from hub.api.tts_api import router as tts_router
from hub.api.agenda_api import router as agenda_router
from hub.api.auth_api import router as auth_router
from hub.api.saude_sync_api import router as saude_sync_router


def create_app() -> FastAPI:
    app = FastAPI(title="AVA Cockpit — Life Mission Control")

    static_dir = pathlib.Path(__file__).resolve().parent / "static"
    if not static_dir.exists():
        static_dir = pathlib.Path("src/hub/static")
    if not static_dir.exists():
        static_dir = pathlib.Path("/app/src/hub/static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(dashboard_router)
    app.include_router(telemetry_router)
    app.include_router(chat_router)
    app.include_router(tts_router)
    app.include_router(agenda_router)
    app.include_router(auth_router)
    app.include_router(saude_sync_router)

    @app.get("/sw.js")
    async def get_service_worker():
        from fastapi.responses import FileResponse
        sw_file = static_dir / "sw.js"
        return FileResponse(sw_file, media_type="application/javascript")

    @app.get("/manifest.json")
    async def get_manifest():
        from fastapi.responses import FileResponse
        manifest_file = static_dir / "manifest.json"
        return FileResponse(manifest_file, media_type="application/manifest+json")

    @app.get("/health")
    async def health():
        return {"status": "ok", "app": "hub"}

    return app


app = create_app()
