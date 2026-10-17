"""Engine do banco e sessões. SQLite em dev/testes; Postgres em produção (DATABASE_URL)."""
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Base
from app.db.urls import is_postgres, sync_url

_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def init_db(db_path: str | None = None, database_url: str | None = None) -> None:
    """Cria o engine e as tabelas. Chamado no startup do app e nos testes."""
    global _engine, _SessionLocal
    url = database_url or (None if db_path else settings.database_url)
    if is_postgres(url):
        # pool pequeno (plano gratuito: 20 conexões) e pre_ping: o serviço gratuito pode ter
        # desligado por inatividade, e uma conexão velha precisa ser descartada.
        _engine = create_engine(sync_url(url), pool_size=settings.db_pool_size,
                                max_overflow=settings.db_max_overflow, pool_pre_ping=True, pool_recycle=300)
    else:
        path = db_path or settings.db_path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: o ADK executa nós síncronos em threads de trabalho.
        _engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(_engine, expire_on_commit=False)


@contextmanager
def db_session() -> Iterator[Session]:
    """Sessão com commit no fim e rollback em erro. Usada por API e nós do agente."""
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
