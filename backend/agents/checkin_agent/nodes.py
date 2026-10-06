"""Nós de CÓDIGO do grafo de check-in (sem LLM).

Regra do desenho: o LLM decide *o que perguntar* e *o que significa*; o código decide
*quando* cada etapa roda e *o que pode ser gravado*. Por isso todo acesso ao banco
mora aqui, e os ids da pessoa vêm do state (injetado pela API a partir do login),
nunca de argumentos do modelo.
"""
from google.adk import Event
from google.adk.agents.context import Context
from google.adk.events import RequestInput

from agents.shared.safety import as_data
from app.config import settings
from app.db import repository as repo
from app.db.models import Member, Team
from app.db.session import db_session
from app.domain import rules
from app.domain.schemas import BlockerLabels, CheckinDraft, ReviewDecision

MAX_CORRECTIONS = 3


def _identity(ctx: Context) -> tuple[int, str]:
    """member_id e team_id foram gravados no state pela API. O modelo não participa."""
    return int(ctx.state["member_id"]), str(ctx.state["team_id"])


def _list_items(texts: list[str]) -> str:
    return "\n".join(f"- {t}" for t in texts) if texts else "(nenhum)"


# --------------------------------------------------------------------- 1. contexto

def load_context(ctx: Context):
    """Carrega o plano de ontem, os impeditivos abertos e as perguntas-base do time."""
    member_id, team_id = _identity(ctx)
    with db_session() as db:
        team = db.get(Team, team_id)
        member = db.get(Member, member_id)
        if team is None or member is None or member.team_id != team_id:
            raise PermissionError("Membro não pertence ao time informado.")
        today = repo.today_for(team)
        previous = repo.last_checkin_before(db, member_id, today)
        plan = [p["summary"] for p in previous.data.get("planned", [])] if previous else []
        imps = repo.open_impediments(db, team_id, member_id)
        open_lines = [
            f"id={i.id}: {i.summary} ({rules.age_label(rules.business_days_between(i.opened_on, today))})"
            for i in imps
        ]
        questions = team.base_questions or repo.DEFAULT_QUESTIONS
        first_name = member.name.split()[0]

    ctx.state["previous_plan"] = as_data(_list_items(plan))
    ctx.state["open_impediments"] = as_data(_list_items(open_lines))
    ctx.state["base_questions"] = "; ".join(questions)
    ctx.state["member_first_name"] = first_name
    ctx.state["corrections"] = 0
    ctx.state["correction"] = ""


# ------------------------------------------------------------ 2. roteamento por bloqueios

def route_blockers(ctx: Context, node_input: CheckinDraft):
    """Guarda o rascunho no state e decide se precisa classificar bloqueios."""
    draft = node_input.model_dump() if isinstance(node_input, CheckinDraft) else dict(node_input)
    route = "has_blockers" if draft.get("blockers") else "no_blockers"
    yield Event(route=route, state={"checkin_draft": draft}, output=draft)


def merge_labels(ctx: Context, node_input: BlockerLabels):
    """Aplica categoria/severidade do classificador ao rascunho (o texto não muda)."""
    draft = dict(ctx.state["checkin_draft"])
    blockers = [dict(b) for b in draft["blockers"]]
    labels = node_input.labels if isinstance(node_input, BlockerLabels) else []
    for label in labels:
        if 0 <= label.index < len(blockers):
            blockers[label.index].update(
                category=label.category, severity=label.severity,
                existing_impediment_id=label.existing_impediment_id,
            )
    draft["blockers"] = blockers
    yield Event(state={"checkin_draft": draft}, output=draft)


# ----------------------------------------------------------- 3. confirmação da pessoa

def ask_confirmation(ctx: Context):
    """Pausa o grafo e mostra o resumo. Só segue quando a pessoa responder."""
    round_ = int(ctx.state.get("corrections", 0))
    yield RequestInput(
        interrupt_id=f"review-{round_}",
        message="Este resumo está certo?",
        payload=ctx.state["checkin_draft"],
        response_schema=ReviewDecision,
    )


def handle_review(ctx: Context, node_input):
    """Recebe a resposta: confirmar segue para gravar; corrigir volta para a conversa.

    Só "confirm" chega a save_checkin. Se a pessoa pedir correção além do limite, o check-in
    é descartado SEM gravar: nunca se grava algo que ela não confirmou.
    """
    decision = _parse_decision(node_input)
    corrections = int(ctx.state.get("corrections", 0))
    if decision.action == "confirm":
        yield Event(route="confirm")
    elif corrections < MAX_CORRECTIONS:
        yield Event(route="correct",
                    state={"corrections": corrections + 1, "correction": as_data(decision.correction)})
    else:
        yield Event(route="discard")


def _parse_decision(value) -> ReviewDecision:
    if isinstance(value, ReviewDecision):
        return value
    if isinstance(value, dict):
        return ReviewDecision(**value)
    text = str(value).strip().lower()
    return ReviewDecision(action="confirm" if text.startswith("conf") else "correct",
                          correction="" if text.startswith("conf") else str(value))


def discard_checkin(ctx: Context):
    """Fim sem gravar: limite de correções atingido."""
    yield Event(state={"discarded": True},
                message="Chegamos ao limite de correções e nada foi salvo. Reabra o check-in para recomeçar.")


# --------------------------------------------------------------------- 4. gravação

def save_checkin(ctx: Context):
    """Única porta de gravação. Só é alcançável pela rota "confirm" do grafo."""
    member_id, team_id = _identity(ctx)
    draft = CheckinDraft(**ctx.state["checkin_draft"])
    with db_session() as db:
        team = db.get(Team, team_id)
        member = db.get(Member, member_id)
        cycle = repo.get_or_create_cycle(db, team)
        checkin = repo.save_checkin(db, cycle=cycle, member=member, draft=draft)
        confirmed_at = checkin.confirmed_at
    yield Event(
        state={"confirmed": True, "checkin_id": checkin.id},
        message=("Check-in salvo. Ele entra no próximo report do time"
                 + (" e vou acompanhar seus impeditivos com você." if draft.blockers else ".")),
    )
