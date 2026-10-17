"""API: identidade, permissões e o fluxo de check-in em SSE (com LLM falso)."""
import json

import pytest
from fastapi.testclient import TestClient
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from agents.checkin_agent import agent as checkin
from app import agent_runner
from app.main import app
from tests.fake_llm import FakeLlm
from tests.test_checkin_graph import DRAFT, LABELS

DIEGO = {"X-User-Email": "diego.rocha@bv.com.br"}
GESTOR = {"X-User-Email": "lucas.barros@bv.com.br"}


@pytest.fixture()
def client(db, monkeypatch):
    monkeypatch.setattr(agent_runner, "_sessions", InMemorySessionService())
    monkeypatch.setattr(agent_runner, "checkin_app", checkin.build_app(
        conversation_model=FakeLlm(script=["Bom dia, Diego!", ("tool", "finish_task", DRAFT)]),
        classifier_model=FakeLlm(script=[LABELS])))
    return TestClient(app)


def sse(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_requires_login(client):
    assert client.get("/api/me").status_code == 401


def test_unknown_email_is_rejected(client):
    assert client.get("/api/me", headers={"X-User-Email": "intruso@x.com"}).status_code == 403


def test_me_lists_memberships(client):
    body = client.get("/api/me", headers=GESTOR).json()
    assert {m["team_id"] for m in body["memberships"]} == {"pagamentos", "onboarding"}


def test_member_cannot_read_other_team_or_use_manager_routes(client):
    assert client.get("/api/teams/onboarding", headers=DIEGO).status_code == 403
    assert client.put("/api/teams/pagamentos", headers=DIEGO,
                      json={"name": "Hack", "timezone": "America/Sao_Paulo"}).status_code == 403
    assert client.post("/api/teams/pagamentos/reports", headers=DIEGO).status_code == 403
    assert client.patch("/api/impediments/1", headers=DIEGO, json={"status": "RESOLVED"}).status_code == 403


def test_member_sees_only_totals_manager_sees_panel(client):
    member_view = client.get("/api/teams/pagamentos/cycles/today", headers=DIEGO).json()
    assert "members" not in member_view and member_view["total"] == 7
    panel = client.get("/api/teams/pagamentos/cycles/today", headers=GESTOR).json()
    assert len(panel["members"]) == 7 and panel["responded"] == 0
    assert any(i["aged"] for i in panel["impediments"])


def test_manager_resolves_impediment_and_changes_severity(client):
    imp = client.get("/api/teams/pagamentos/cycles/today", headers=GESTOR).json()["impediments"][0]
    r = client.patch(f"/api/impediments/{imp['id']}", headers=GESTOR,
                     json={"status": "RESOLVED", "note": "infra reiniciou", "severity": "LOW"})
    assert r.json()["status"] == "RESOLVED" and r.json()["note"] == "infra reiniciou"
    after = client.get("/api/teams/pagamentos/cycles/today", headers=GESTOR).json()
    assert imp["id"] not in [i["id"] for i in after["impediments"]]
    assert after["resolved_today"][0]["note"] == "infra reiniciou"


def test_team_config_and_members(client):
    r = client.put("/api/teams/pagamentos", headers=GESTOR, json={
        "name": "Squad Pagamentos", "timezone": "America/Recife", "cutoff_time": "09:30",
        "base_questions": ["O que avançou?"]})
    assert r.json()["timezone"] == "America/Recife"
    assert client.put("/api/teams/pagamentos", headers=GESTOR,
                      json={"name": "X1", "timezone": "Marte/Olympus"}).status_code == 422
    added = client.post("/api/teams/pagamentos/members", headers=GESTOR,
                        json={"name": "Nova Pessoa", "email": "nova@bv.com.br"})
    assert added.status_code == 201
    assert client.get("/api/me", headers={"X-User-Email": "nova@bv.com.br"}).status_code == 200


def test_checkin_flow_over_sse_and_session_isolation(client):
    sid = client.post("/api/teams/pagamentos/checkin/session", headers=DIEGO, json={}).json()["session_id"]

    # outra pessoa não pode usar a sessão do Diego
    ana = {"X-User-Email": "ana.souza@bv.com.br"}
    assert client.post("/api/teams/pagamentos/checkin/messages", headers=ana,
                       json={"session_id": sid, "text": "oi"}).status_code == 403

    first = sse(client.post("/api/teams/pagamentos/checkin/messages", headers=DIEGO,
                            json={"session_id": sid, "text": "Iniciar check-in"}))
    assert first[0]["type"] == "agent"

    second = sse(client.post("/api/teams/pagamentos/checkin/messages", headers=DIEGO,
                             json={"session_id": sid, "text": "Terminei o login."}))
    review = next(e for e in second if e["type"] == "review")
    assert review["draft"]["blockers"][0]["severity"] == "HIGH"

    ctx = client.get("/api/teams/pagamentos/checkin/context", headers=DIEGO).json()
    assert ctx["today"] is None  # nada gravado antes de confirmar

    done = sse(client.post("/api/teams/pagamentos/checkin/messages", headers=DIEGO, json={
        "session_id": sid, "invocation_id": review["invocation_id"],
        "review": {"interrupt_id": review["interrupt_id"], "action": "confirm"}}))
    assert done[-1]["type"] == "saved"

    ctx = client.get("/api/teams/pagamentos/checkin/context", headers=DIEGO).json()
    assert ctx["today"]["data"]["planned"][0]["summary"] == "Integrar login com autenticação"
    status = client.get("/api/teams/pagamentos/cycles/today", headers=GESTOR).json()
    assert status["responded"] == 1


def test_unknown_api_route_is_json_404_not_the_frontend(client, tmp_path, monkeypatch):
    """Com o front estático montado, rotas inexistentes de /api devem dar 404 (e não o index.html)."""
    from fastapi import HTTPException

    from app import main
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>spa</html>")
    monkeypatch.setattr(main, "STATIC_DIR", static)
    handler = next((r.endpoint for r in main.app.router.routes if getattr(r, "path", "") == "/{path:path}"), None)
    if handler is None:
        pytest.skip("front estático não foi compilado (backend/static ausente)")
    with pytest.raises(HTTPException) as e:
        handler("api/nao-existe")
    assert e.value.status_code == 404
    assert handler("painel").status_code == 200  # rota do SPA continua servindo o index.html
