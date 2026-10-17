"""Travas de custo: cada chamada de LLM custa dinheiro, então os limites precisam realmente barrar."""
import json

import pytest
from fastapi.testclient import TestClient
from google.adk.sessions import InMemorySessionService

from agents.checkin_agent import agent as checkin
from agents.shared.models import generation_config
from app import agent_runner
from app.config import settings
from app.db import repository as repo
from app.db.models import Report
from app.db.session import db_session
from app.main import app
from tests.fake_llm import FakeLlm
from tests.test_checkin_graph import DRAFT, LABELS

DIEGO = {"X-User-Email": "diego.rocha@bv.com.br"}
GESTOR = {"X-User-Email": "lucas.barros@bv.com.br"}


@pytest.fixture()
def client(db, monkeypatch):
    monkeypatch.setattr(agent_runner, "_sessions", InMemorySessionService())
    monkeypatch.setattr(agent_runner, "_message_counts", {})
    monkeypatch.setattr(agent_runner, "_generating", set())
    monkeypatch.setattr(agent_runner, "checkin_app", checkin.build_app(
        conversation_model=FakeLlm(script=["Bom dia!", ("tool", "finish_task", DRAFT)]),
        classifier_model=FakeLlm(script=[LABELS])))
    return TestClient(app)


def test_every_llm_call_has_an_output_token_ceiling():
    assert generation_config(0.2, model="gemini-3.1-flash-lite").max_output_tokens == settings.max_output_tokens
    assert generation_config(0.2, model="gemini-2.5-flash").max_output_tokens == settings.max_output_tokens


def test_runs_are_capped_in_llm_calls_not_left_at_the_adk_default_of_500(monkeypatch):
    seen = {}

    class SpyRunner:
        async def run_async(self, **kwargs):
            seen.update(kwargs)
            return
            yield  # noqa: B901  (gerador vazio)

    monkeypatch.setattr(agent_runner, "_runner", lambda app: SpyRunner())
    import asyncio

    async def drain(gen):
        return [e async for e in gen]

    asyncio.run(drain(agent_runner.stream_checkin("a@b.com", "s1", text="oi")))
    assert seen["run_config"].max_llm_calls == settings.max_llm_calls_checkin < 500


def test_checkin_conversation_stops_after_the_message_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "max_checkin_messages", 2)
    sid = client.post("/api/teams/pagamentos/checkin/session", headers=DIEGO, json={}).json()["session_id"]
    url = "/api/teams/pagamentos/checkin/messages"
    assert client.post(url, headers=DIEGO, json={"session_id": sid, "text": "um"}).status_code == 200
    assert client.post(url, headers=DIEGO, json={"session_id": sid, "text": "dois"}).status_code == 200
    blocked = client.post(url, headers=DIEGO, json={"session_id": sid, "text": "três"})
    assert blocked.status_code == 429 and "limite" in blocked.json()["detail"].lower()


def test_report_daily_limit_blocks_before_any_llm_call(client, monkeypatch):
    monkeypatch.setattr(settings, "max_reports_per_day", 2)
    calls = []
    monkeypatch.setattr(agent_runner, "stream_report", lambda m: calls.append(m) or iter(()))
    with db_session() as db:
        team = db.get(repo.Team, "pagamentos")
        cycle = repo.get_or_create_cycle(db, team)
        manager = next(m for m in repo.team_members(db, "pagamentos") if m.role == "manager")
        for v in (1, 2):
            db.add(Report(cycle_id=cycle.id, team_id="pagamentos", version=v, generated_by=manager.id,
                          content={}, prompt_version="t"))
    r = client.post("/api/teams/pagamentos/reports", headers=GESTOR)
    assert r.status_code == 429 and not calls  # nenhuma geração foi iniciada


def test_second_report_cannot_start_while_one_is_running(client, monkeypatch):
    monkeypatch.setattr(agent_runner, "_generating", {"pagamentos"})
    r = client.post("/api/teams/pagamentos/reports", headers=GESTOR)
    assert r.status_code == 409
