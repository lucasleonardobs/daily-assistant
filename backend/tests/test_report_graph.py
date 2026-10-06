"""Grafo do report com LLM falso: fan-out/join, portão de evidência em código e versões."""
import json

import pytest
from google.adk.models import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents.report_agent import agent as report
from app.db import repository as repo
from app.db.models import Report
from app.db.session import db_session
from tests.fake_llm import FakeLlm


class RoutedLlm(FakeLlm):
    """Responde conforme o agente (identificado por uma palavra do prompt de sistema)."""
    by_agent: dict = {}

    async def generate_content_async(self, llm_request, stream=False):
        system = str(llm_request.config.system_instruction)
        for marker, items in self.by_agent.items():
            if marker in system:
                idx = self.counters.get(marker, 0)
                self.counters[marker] = idx + 1
                item = items[min(idx, len(items) - 1)]
                yield LlmResponse(
                    content=types.Content(role="model", parts=[types.Part(text=json.dumps(item))]))
                return
        raise AssertionError(f"agente não reconhecido: {system[:80]}")

    counters: dict = {}


async def generate(db, evidence_for_draft, critic_script):
    team = db.get(repo.Team, "pagamentos")
    manager = next(m for m in repo.team_members(db, "pagamentos") if m.role == "manager")
    cycle_id = f"pagamentos_{repo.today_for(team)}"
    db.commit()
    llm = RoutedLlm(by_agent={
        "PROGRESSO": [{"themes": []}], "IMPEDITIVOS": [{"findings": [], "shared_dependencies": []}],
        "RISCOS": [{"risks": []}], "RECOMENDAÇÕES": [{"items": []}],
        "REPORT diário": [{"actions": [{"text": "Acionar infra", "tag": "Alta", "high_priority": True,
                                         "suggested_owner": "Gestor", "evidence_ids": evidence_for_draft}],
                           "progress": [], "impediments": [], "risks": []}],
        "REVISOR": critic_script}, counters={})
    app = report.build_app(model=llm)
    sessions = InMemorySessionService()
    runner = Runner(app=app, session_service=sessions)
    s = await sessions.create_session(app_name="report_agent", user_id="m",
                                      state={"member_id": manager.id, "team_id": "pagamentos"})
    async for _ in runner.run_async(user_id="m", session_id=s.id,
                                    new_message=types.Content(role="user", parts=[types.Part(text="Gerar")])):
        pass
    return cycle_id


async def test_invalid_evidence_is_blocked_by_code_even_if_critic_approves(db):
    cycle_id = await generate(db, ["id-que-nao-existe"], [{"approved": True, "problems": []}])
    with db_session() as fresh:
        r = fresh.query(Report).filter_by(cycle_id=cycle_id).one()
        # 3 voltas esgotadas: publicado, mas marcado como revisão incompleta
        assert r.incomplete_review is True


async def test_valid_evidence_publishes_clean_version(db):
    ana_imp = repo.open_impediments(db, "pagamentos")[0]
    cycle_id = await generate(db, [ana_imp.checkin_id], [{"approved": True, "problems": []}])
    with db_session() as fresh:
        r = fresh.query(Report).filter_by(cycle_id=cycle_id).one()
        assert r.incomplete_review is False and r.version == 1
        assert r.content["actions"][0]["evidence_ids"] == [ana_imp.checkin_id]
        assert "people" in r.content and "participation" in r.content
