# Um serviço só: Angular compilado + API FastAPI + agentes ADK.
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx ng build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist/frontend/browser ./static

# Produção: login pelo IAP (DEV_MODE=false). Bancos SQLite em /data (monte um volume).
ENV DEV_MODE=false DB_PATH=/data/app.db SESSIONS_DB_PATH=/data/sessions.db PORT=8080
VOLUME /data
CMD ["sh", "-c", "uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
