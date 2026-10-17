"""Sessões do ADK no Postgres (asyncpg + SSL). Só roda com TEST_DATABASE_URL apontando para um banco descartável."""
import os

import pytest
from google.adk.sessions import DatabaseSessionService

from app.db.urls import async_url

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="sem TEST_DATABASE_URL")


async def test_session_roundtrip_with_state():
    service = DatabaseSessionService(async_url(os.environ["TEST_DATABASE_URL"]), pool_size=2, max_overflow=1)
    created = await service.create_session(app_name="checkin_agent", user_id="ana@bv.com.br", session_id="pg-1",
                                           state={"member_id": 7, "team_id": "pagamentos"})
    loaded = await service.get_session(app_name="checkin_agent", user_id="ana@bv.com.br", session_id="pg-1")
    assert loaded.state["member_id"] == 7 and created.id == "pg-1"
    # outro usuário não enxerga a sessão
    assert await service.get_session(app_name="checkin_agent", user_id="outro@bv.com.br", session_id="pg-1") is None
