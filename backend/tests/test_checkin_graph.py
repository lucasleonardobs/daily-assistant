"""Percorre o grafo de check-in de ponta a ponta com um LLM falso."""
import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents.checkin_agent import agent as checkin
from app.db import repository as repo
from app.db.models import Checkin, Impediment
from app.db.session import db_session
from tests.fake_llm import FakeLlm

DRAFT = {
    "done": [{"summary": "Tela de login finalizada", "related_to_previous_plan": True}],
    "planned": [{"summary": "Integrar login com autenticação"}],
    "blockers": [{"summary": "Homologação fora do ar", "category": "OTHER", "severity": "MEDIUM",
                  "needs_from": "infra", "existing_impediment_id": None}],
    "resolved_impediment_ids": [], "risks": [], "notes": "",
}
LABELS = {"labels": [{"index": 0, "category": "ENVIRONMENT", "severity": "HIGH", "existing_impediment_id": 2}]}


def text(content: types.Content | None) -> str:
    return "".join(p.text or "" for p in content.parts) if content and content.parts else ""


async def run(runner, session_id, message, invocation_id=None):
    events = []
    async for e in runner.run_async(user_id="diego", session_id=session_id, new_message=message,
                                    invocation_id=invocation_id):
        events.append(e)
    return events


def user(msg: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=msg)])


@pytest.mark.asyncio
async def test_checkin_happy_path(db):
    team = db.get(repo.Team, "pagamentos")
    diego = next(m for m in repo.team_members(db, "pagamentos") if m.name == "Diego Rocha")
    db.commit()

    app = checkin.build_app(
        conversation_model=FakeLlm(script=[
            "Bom dia, Diego. Ontem você ia finalizar a tela de login. Como foi?",
            ("tool", "finish_task", DRAFT),
        ]),
        classifier_model=FakeLlm(script=[LABELS]),
    )
    sessions = InMemorySessionService()
    runner = Runner(app=app, session_service=sessions)
    s = await sessions.create_session(app_name="checkin_agent", user_id="diego",
                                      state={"member_id": diego.id, "team_id": "pagamentos"})

    # 1) sinal de início: o agente abre a conversa citando o plano de ontem
    events = await run(runner, s.id, user("Iniciar check-in"))
    assert any("tela de login" in text(e.content) for e in events)

    # 2) a pessoa responde → agente conclui → classificador → pausa pedindo confirmação
    events = await run(runner, s.id, user("Terminei o login, PR em revisão. Homologação segue fora."))
    asks = [fc for e in events for fc in e.get_function_calls() if fc.name == "adk_request_input"]
    assert asks, [text(e.content) for e in events]
    ask = asks[0]
    # categoria/severidade vieram do classificador, não do rascunho
    assert ask.args["payload"]["blockers"][0]["severity"] == "HIGH"
    assert ask.args["payload"]["blockers"][0]["category"] == "ENVIRONMENT"
    assert db.query(Checkin).filter_by(member_id=diego.id, day=repo.today_for(team)).count() == 0  # nada gravado ainda

    # 3) confirma → grava
    resume = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
        id=ask.id, name="adk_request_input", response={"action": "confirm", "correction": ""}))])
    events = await run(runner, s.id, resume, invocation_id=events[-1].invocation_id)
    assert any("Check-in salvo" in text(e.content) for e in events)

    with db_session() as fresh:
        saved = fresh.query(Checkin).filter_by(member_id=diego.id, day=repo.today_for(team)).one()
        assert saved.data["planned"][0]["summary"] == "Integrar login com autenticação"
        imp = fresh.get(Impediment, 2)
        assert imp.severity == "HIGH" and imp.status == "OPEN"


@pytest.mark.asyncio
async def test_correction_goes_back_to_conversation_then_confirms_without_correction_field(db):
    diego = next(m for m in repo.team_members(db, "pagamentos") if m.name == "Diego Rocha")
    db.commit()
    fixed = {**DRAFT, "blockers": [], "notes": "PR é o #482"}
    conv = FakeLlm(script=["Bom dia!", ("tool", "finish_task", {**DRAFT, "blockers": []}),
                           ("tool", "finish_task", fixed)])
    app = checkin.build_app(conversation_model=conv, classifier_model=FakeLlm(script=[LABELS]))
    sessions = InMemorySessionService()
    runner = Runner(app=app, session_service=sessions)
    s = await sessions.create_session(app_name="checkin_agent", user_id="diego",
                                      state={"member_id": diego.id, "team_id": "pagamentos"})

    await run(runner, s.id, user("Iniciar check-in"))
    events = await run(runner, s.id, user("Terminei o login."))
    ask = [fc for e in events for fc in e.get_function_calls() if fc.name == "adk_request_input"][0]

    # pessoa corrige → volta à conversa e produz um novo resumo, com nova pausa
    correct = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
        id=ask.id, name="adk_request_input", response={"action": "correct", "correction": "O PR é o #482"}))])
    events = await run(runner, s.id, correct, invocation_id=events[-1].invocation_id)
    asks = [fc for e in events for fc in e.get_function_calls() if fc.name == "adk_request_input"]
    assert asks and asks[0].args["payload"]["notes"] == "PR é o #482"
    assert asks[0].id != ask.id  # nova rodada de confirmação

    # confirma omitindo o campo "correction"
    confirm = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
        id=asks[0].id, name="adk_request_input", response={"action": "confirm"}))])
    events = await run(runner, s.id, confirm, invocation_id=events[-1].invocation_id)
    assert any("Check-in salvo" in text(e.content) for e in events)


@pytest.mark.asyncio
async def test_exceeding_correction_limit_discards_without_saving(db):
    """Regressão: corrigir além do limite NUNCA pode gravar um check-in não confirmado."""
    diego = next(m for m in repo.team_members(db, "pagamentos") if m.name == "Diego Rocha")
    team = db.get(repo.Team, "pagamentos")
    db.commit()
    draft = {**DRAFT, "blockers": []}
    conv = FakeLlm(script=["Bom dia!"] + [("tool", "finish_task", draft)] * 6)
    app = checkin.build_app(conversation_model=conv, classifier_model=FakeLlm(script=[LABELS]))
    sessions = InMemorySessionService()
    runner = Runner(app=app, session_service=sessions)
    s = await sessions.create_session(app_name="checkin_agent", user_id="diego",
                                      state={"member_id": diego.id, "team_id": "pagamentos"})
    await run(runner, s.id, user("Iniciar check-in"))
    events = await run(runner, s.id, user("Terminei o login."))
    for _ in range(4):  # 3 correções permitidas + 1 além do limite
        ask = [fc for e in events for fc in e.get_function_calls() if fc.name == "adk_request_input"][0]
        resp = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            id=ask.id, name="adk_request_input", response={"action": "correct", "correction": "outra vez"}))])
        events = await run(runner, s.id, resp, invocation_id=events[-1].invocation_id)
    assert any("limite de correções" in text(e.content) for e in events)
    assert db.query(Checkin).filter_by(member_id=diego.id, day=repo.today_for(team)).count() == 0
