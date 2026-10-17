import os

import pytest

from app.db import session as session_mod
from app.db.models import Base
from app.db.session import db_session, init_db
from app.seed import seed


@pytest.fixture()
def db(tmp_path):
    """Banco já com o seed do protótipo. SQLite temporário; ou Postgres se TEST_DATABASE_URL existir
    (use um banco DESCARTÁVEL: as tabelas são recriadas a cada teste)."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        init_db(database_url=url)
        Base.metadata.drop_all(session_mod._engine)
        Base.metadata.create_all(session_mod._engine)
    else:
        init_db(str(tmp_path / "test.db"))
    with db_session() as s:
        seed(s)
    with db_session() as s:
        yield s
