"""Executa os agentes ADK dentro do app e traduz os eventos para o front-end.

O front não conhece o protocolo do ADK: recebe eventos simples via SSE:
  {"type": "agent",  "text": ...}                        mensagem do agente
  {"type": "review", "interrupt_id", "invocation_id", "draft"}   resumo para confirmar/corrigir
  {"type": "saved",  "text": ..., "checkin_id": ...}     check-in gravado
  {"type": "discarded", "text": ...}                      limite de correções: nada foi gravado
  {"type": "step",   "step": n}                          etapa do report (0..4)
  {"type": "done",   "report_id": ...}                   report publicado
  {"type": "error",  "text": ...}
Identidade (member_id/team_id) entra no state da sessão aqui, nunca pelo cliente.
"""
import logging
from collections.abc import AsyncIterator

from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import types

from agents.checkin_agent.agent import app as checkin_app
from agents.report_agent.agent import app as report_app
from app.config import settings
from app.db.models import Member

log = logging.getLogger("daily.agents")

REPORT_STEPS = ["Carregando check-ins", "Analisando progresso", "Cruzando bloqueios",
                "Revisão do crítico", "Publicando"]
_STEP_OF_NODE = {"load_report_context": 0, "progress_analyst": 1, "blocker_analyst": 2,
                 "risk_analyst": 2, "insights_agent": 2, "report_writer": 2,
                 "report_critic": 3, "review_gate": 3, "publish_report": 4}

_sessions: BaseSessionService | None = None


def sessions() -> BaseSessionService:
    global _sessions
    if _sessions is None:
        from pathlib import Path
        Path(settings.sessions_db_path).parent.mkdir(parents=True, exist_ok=True)
        _sessions = SqliteSessionService(settings.sessions_db_path)
    return _sessions


def _runner(app) -> Runner:
    return Runner(app=app, session_service=sessions())


def _node_name(event) -> str:
    path = event.node_info.path if event.node_info else ""
    return path.split("/")[-1].split("@")[0] if path else ""


# ------------------------------------------------------------------- check-in

async def create_checkin_session(member: Member, cycle_id: str, *, fresh: bool = False) -> str:
    """Cria (ou retoma) a sessão do dia da pessoa. `fresh` abre uma nova para editar o check-in."""
    session_id = f"{cycle_id}:{member.id}"
    if fresh:
        import time
        session_id += f":{int(time.time())}"
    existing = await sessions().get_session(app_name=checkin_app.name, user_id=member.email,
                                            session_id=session_id)
    if existing is None:
        await sessions().create_session(
            app_name=checkin_app.name, user_id=member.email, session_id=session_id,
            state={"member_id": member.id, "team_id": member.team_id})
    return session_id


async def stream_checkin(email: str, session_id: str, *, text: str | None = None,
                         review: dict | None = None, invocation_id: str | None = None
                         ) -> AsyncIterator[dict]:
    """Uma rodada da conversa: texto livre da pessoa OU resposta ao resumo (review)."""
    if review:
        message = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            id=review["interrupt_id"], name="adk_request_input",
            response={"action": review["action"], "correction": review.get("correction", "")}))])
    else:
        message = types.Content(role="user", parts=[types.Part(text=text or "")])
    try:
        async for event in _runner(checkin_app).run_async(
                user_id=email, session_id=session_id, new_message=message,
                invocation_id=invocation_id if review else None):
            for out in _checkin_event_to_messages(event):
                yield out
    except Exception:
        log.exception("Falha no check-in")
        yield {"type": "error", "text": "Não consegui processar agora. Tente de novo em instantes."}


def _checkin_event_to_messages(event) -> list[dict]:
    for fc in event.get_function_calls():
        if fc.name == "adk_request_input":
            return [{"type": "review", "interrupt_id": fc.id, "invocation_id": event.invocation_id,
                     "draft": (fc.args or {}).get("payload")}]
    text = "".join(p.text or "" for p in (event.content.parts if event.content else []))
    if not text or event.partial or event.get_function_calls() or event.get_function_responses():
        return []
    if event.author == "checkin_conversation":
        return [{"type": "agent", "text": text}]
    if _node_name(event) == "save_checkin":
        return [{"type": "saved", "text": text,
                 "checkin_id": (event.actions.state_delta or {}).get("checkin_id")}]
    if _node_name(event) == "discard_checkin":
        return [{"type": "discarded", "text": text}]
    return []  # saídas internas (classificador etc.) não vão para a tela


# --------------------------------------------------------------------- report

async def stream_report(manager: Member) -> AsyncIterator[dict]:
    """Roda o grafo do report e informa a etapa atual. O gestor aciona; nada é agendado."""
    session = await sessions().create_session(
        app_name=report_app.name, user_id=manager.email,
        state={"member_id": manager.id, "team_id": manager.team_id})
    step, report_id = -1, None
    try:
        async for event in _runner(report_app).run_async(
                user_id=manager.email, session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text="Gerar report")])):
            idx = _STEP_OF_NODE.get(_node_name(event))
            if idx is not None and idx > step:
                step = idx
                yield {"type": "step", "step": step}
            report_id = (event.actions.state_delta or {}).get("report_id", report_id)
        if report_id is None:
            raise RuntimeError("O grafo terminou sem publicar o report.")
        yield {"type": "done", "report_id": report_id}
    except Exception:
        log.exception("Falha ao gerar report")
        yield {"type": "error", "text": "Não consegui gerar o report agora. Tente de novo."}
