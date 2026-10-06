import pytest

from app.db import session as session_mod
from app.db.session import db_session, init_db
from app.seed import seed


@pytest.fixture()
def db(tmp_path):
    """Banco SQLite temporário já com o seed do protótipo."""
    init_db(str(tmp_path / "test.db"))
    with db_session() as s:
        seed(s)
    with db_session() as s:
        yield s
