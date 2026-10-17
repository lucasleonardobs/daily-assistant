"""App FastAPI: API própria + front-end Angular estático, tudo em um serviço.

Rodar: `uv run uvicorn app.main:app --reload`
Os agentes ADK rodam dentro deste processo (app/agent_runner.py). Para conversar com
eles isoladamente, use o console do ADK: `uv run adk web agents`.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.api import auth, checkin, cycles, me, reports, teams
from app.bootstrap import bootstrap_if_empty, check_production_settings
from app.auth import COOKIE
from app.config import BACKEND_DIR, settings
from app.security import same_origin
from app.db.session import db_session, init_db
from app.seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
STATIC_DIR = BACKEND_DIR / "static"  # onde o Dockerfile copia o build do Angular


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.dev_mode:
        check_production_settings()
    init_db()
    with db_session() as db:
        if settings.dev_mode:
            seed(db)  # idempotente: só popula banco vazio
        else:
            bootstrap_if_empty(db)  # primeiro time/gestor a partir de variáveis de ambiente
    yield


app = FastAPI(title="Daily Assíncrona", lifespan=lifespan, docs_url="/api/docs" if settings.dev_mode else None,
              redoc_url=None, openapi_url="/api/openapi.json" if settings.dev_mode else None)

@app.middleware("http")
async def csrf_guard(request: Request, call_next):
    """Requisições que alteram dados e carregam o cookie de sessão precisam vir do próprio site."""
    if (request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/")
            and COOKIE in request.cookies and not same_origin(request.headers.get("origin"), request.headers.get("host"))):
        return JSONResponse({"detail": "Origem não permitida."}, status_code=403)
    return await call_next(request)


for router in (auth.router, me.router, teams.router, cycles.router, checkin.router, reports.router):
    app.include_router(router)


@app.get("/api/health")
def health():
    """Liveness: não toca no banco (o Postgres gratuito pode estar dormindo)."""
    return {"status": "ok"}


@app.get("/api/health/db")
def health_db():
    from sqlalchemy import text
    with db_session() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok"}


if STATIC_DIR.exists():
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        """Serve o Angular; qualquer rota desconhecida cai no index.html (roteamento do SPA)."""
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Rota não encontrada.")  # a API nunca devolve HTML
        file = (STATIC_DIR / path).resolve()
        if path and STATIC_DIR in file.parents and file.is_file():
            return FileResponse(file)
        return FileResponse(STATIC_DIR / "index.html")
