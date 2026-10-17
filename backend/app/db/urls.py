"""Normaliza a URL do banco para cada driver.

Provedores (Aiven, Railway, Heroku) entregam `postgres://...?sslmode=require`. O SQLAlchemy precisa do
driver explícito, e o asyncpg (sessões do ADK) usa `ssl=` em vez de `sslmode=`.
"""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def is_postgres(url: str | None) -> bool:
    return bool(url) and url.split(":", 1)[0].split("+", 1)[0] in ("postgres", "postgresql")


def _swap(url: str, driver: str, ssl_key: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    mode = query.pop("sslmode", None) or query.pop("ssl", None)
    if mode and mode != "disable":
        query[ssl_key] = "require" if ssl_key == "ssl" else mode
    return urlunsplit((f"postgresql+{driver}", parts.netloc, parts.path, urlencode(query), ""))


def sync_url(url: str) -> str:
    """Para o SQLAlchemy síncrono (dados do produto)."""
    return _swap(url, "psycopg", "sslmode")


def async_url(url: str) -> str:
    """Para o SQLAlchemy assíncrono (sessões do ADK)."""
    return _swap(url, "asyncpg", "ssl")
