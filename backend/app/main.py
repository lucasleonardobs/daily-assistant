"""App FastAPI: API própria + front-end Angular estático, tudo em um serviço.

Rodar: `uv run uvicorn app.main:app --reload`
Os agentes ADK rodam dentro deste processo (app/agent_runner.py). Para conversar com
eles isoladamente, use o console do ADK: `uv run adk web agents`.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api import checkin, cycles, me, reports, teams
from app.config import BACKEND_DIR, settings
from app.db.session import db_session, init_db
from app.seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
STATIC_DIR = BACKEND_DIR / "static"  # onde o Dockerfile copia o build do Angular


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if settings.dev_mode:
        with db_session() as db:
            seed(db)  # idempotente: só popula banco vazio
    yield


app = FastAPI(title="Daily Assíncrona", lifespan=lifespan, docs_url="/api/docs" if settings.dev_mode else None,
              redoc_url=None, openapi_url="/api/openapi.json" if settings.dev_mode else None)

for router in (me.router, teams.router, cycles.router, checkin.router, reports.router):
    app.include_router(router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


if STATIC_DIR.exists():
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        """Serve o Angular; qualquer rota desconhecida cai no index.html (roteamento do SPA)."""
        file = (STATIC_DIR / path).resolve()
        if path and STATIC_DIR in file.parents and file.is_file():
            return FileResponse(file)
        return FileResponse(STATIC_DIR / "index.html")
