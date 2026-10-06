"""Nós de CÓDIGO do grafo de report (sem LLM).

O código monta o contexto com fatos já calculados, valida a evidência e grava.
Os LLMs só interpretam e escrevem.
"""
import json
from datetime import timezone

from google.adk import Event
from google.adk.agents.context import Context

from agents.shared.safety import PROMPT_VERSION, as_data
from app.config import settings
from app.db import repository as repo
from app.db.models import Checkin, Impediment, Member, Report, Team
from app.db.session import db_session
from app.domain import rules
from app.domain.schemas import Critique, Recommendations, ReportDraft

MAX_REVISIONS = 3


def _checkin_view(c: Checkin, names: dict[int, str]) -> dict:
    d = c.data
    return {
        "evidence_id": c.id, "pessoa": names.get(c.member_id, "?"), "dia": c.day.isoformat(),
        "feito": [x["summary"] for x in d.get("done", [])],
        "planejado": [x["summary"] for x in d.get("planned", [])],
        "bloqueios": [{"texto": b["summary"], "categoria": b["category"], "severidade": b["severity"],
                       "precisa_de": b.get("needs_from", "")} for b in d.get("blockers", [])],
        "riscos": [{"texto": r["summary"], "tipo": r["type"]} for r in d.get("risks", [])],
        "notas": d.get("notes", ""),
    }


# ------------------------------------------------------------- 1. contexto + fatos

def load_report_context(ctx: Context):
    """Reúne check-ins, impeditivos e fatos calculados em código. Nada disso passa pelo LLM."""
    team_id, member_id = str(ctx.state["team_id"]), int(ctx.state["member_id"])
    with db_session() as db:
        team = db.get(Team, team_id)
        manager = db.get(Member, member_id)
        if manager is None or manager.team_id != team_id or manager.role != "manager":
            raise PermissionError("Só gestores do time geram report.")
        today = repo.today_for(team)
        prev_day = rules.previous_business_day(today)
        members = repo.team_members(db, team_id)
        names = {m.id: m.name for m in members}

        todays = repo.checkins_of_day(db, team_id, today)
        yesterdays = repo.checkins_of_day(db, team_id, prev_day)
        yesterday_by_member = {c.member_id: c for c in yesterdays}

        open_imps = repo.open_impediments(db, team_id)
        imp_views = [repo.impediment_view(i, today, names, settings.aged_threshold_days) for i in open_imps]
        resolved = [i for i in db.query(Impediment).filter(Impediment.team_id == team_id,
                                                           Impediment.status == "RESOLVED")
                    if i.resolved_at and i.resolved_at.astimezone(timezone.utc).date() >= prev_day]

        repeated, unfulfilled = [], []
        for c in todays:
            history = repo.recent_checkins(db, c.member_id, today, limit=3)
            repeated += [{"pessoa": names[c.member_id], "item": item, "dias_seguidos": streak,
                          "evidence_id": c.id}
                         for item, streak in rules.repeated_items(
                             [p["summary"] for p in c.data.get("planned", [])],
                             [[p["summary"] for p in h.data.get("planned", [])] for h in history])]
            before = yesterday_by_member.get(c.member_id)
            if before:
                for item in rules.unfulfilled_plan(
                        [p["summary"] for p in before.data.get("planned", [])],
                        [x["summary"] for x in c.data.get("done", [])],
                        [p["summary"] for p in c.data.get("planned", [])]):
                    unfulfilled.append({"pessoa": names[c.member_id], "item": item, "evidence_id": before.id})

        responded_ids = {c.member_id for c in todays}
        evidence_ids = {c.id for c in todays} | {c.id for c in yesterdays} | {i["checkin_id"] for i in imp_views}
        context = {
            "hoje": today.isoformat(),
            "limite_envelhecido_dias_uteis": settings.aged_threshold_days,
            "checkins_hoje": [_checkin_view(c, names) for c in todays],
            "checkins_dia_util_anterior": [_checkin_view(c, names) for c in yesterdays],
            "impeditivos_abertos": [{
                "id": i["id"], "pessoa": i["reporter"], "texto": i["summary"], "severidade": i["severity"],
                "idade": i["age_label"], "envelhecido": i["aged"], "precisa_de": i["needs_from"],
                "evidence_id": i["checkin_id"]} for i in imp_views],
            "resolvidos_desde_o_ultimo_dia_util": [
                {"pessoa": names.get(i.member_id, "?"), "texto": i.summary, "nota": i.note,
                 "evidence_id": i.checkin_id} for i in resolved],
            "fatos_calculados": {"itens_repetidos_no_plano": repeated, "plano_de_ontem_nao_citado": unfulfilled},
        }
        evidence_ids |= {r["evidence_id"] for r in context["resolvidos_desde_o_ultimo_dia_util"]}

        # Participação e detalhe por pessoa NÃO passam pelo LLM: são montados direto dos dados.
        participation = {
            "responded": [names[m.id] for m in members if m.id in responded_ids],
            "pending": [m.name for m in members if m.role == "member" and m.id not in responded_ids],
        }
        people = [{"name": names[c.member_id], "checkin_id": c.id,
                   "confirmed_at": repo.utc_iso(c.confirmed_at),
                   "done": "; ".join(x["summary"] for x in c.data.get("done", [])) or "—",
                   "planned": "; ".join(x["summary"] for x in c.data.get("planned", [])) or "—",
                   "blocker": "; ".join(b["summary"] for b in c.data.get("blockers", [])) or "Nenhum"}
                  for c in todays]
        evidence_labels = {eid: _evidence_label(db, eid, names) for eid in evidence_ids}

    yield Event(
        state={
            "report_context": as_data(json.dumps(context, ensure_ascii=False, indent=1)),
            "evidence_ids": sorted(evidence_ids),
            "evidence_labels": evidence_labels,
            "participation": participation,
            "people": people,
            "revisions": 0,
            "critique_feedback": "",
            "report_draft": "",
        },
        output="Gere a análise do dia.",  # entrada dos analistas (um agente precisa de uma mensagem)
    )


def _evidence_label(db, evidence_id: str, names: dict[int, str]) -> str:
    c = db.get(Checkin, evidence_id)
    return f"check-in de {names.get(c.member_id, '?')} · {c.day.strftime('%d/%m')}" if c else evidence_id


# ------------------------------------------------------------- 2. análises e redação

def collect_analyses(ctx: Context, node_input: dict):
    """Junta as 3 análises (que rodaram em paralelo) num texto para os próximos agentes."""
    analyses = {name: (v.model_dump() if hasattr(v, "model_dump") else v) for name, v in node_input.items()}
    yield Event(state={"analyses": as_data(json.dumps(analyses, ensure_ascii=False, indent=1))},
                output="Gere as recomendações.")


def start_writing(ctx: Context, node_input: Recommendations):
    recs = node_input.model_dump() if hasattr(node_input, "model_dump") else node_input
    yield Event(state={"recommendations": as_data(json.dumps(recs, ensure_ascii=False, indent=1))},
                output="Escreva o report.")


def save_draft(ctx: Context, node_input: ReportDraft):
    """Guarda o rascunho (para revisão) e o entrega ao crítico."""
    draft = node_input.model_dump() if hasattr(node_input, "model_dump") else node_input
    yield Event(state={"report_draft_data": draft, "report_draft": as_data(json.dumps(draft, ensure_ascii=False))},
                output=draft)


# --------------------------------------------------------------------- 3. portão de revisão

def _evidence_problems(draft: dict, valid_ids: set[str]) -> list[str]:
    problems = []

    def check(where: str, ids: list[str]):
        if not ids:
            problems.append(f"{where}: sem evidence_ids.")
        for i in ids:
            if i not in valid_ids:
                problems.append(f"{where}: evidence_id inexistente '{i}'.")

    for a in draft.get("actions", []):
        check(f"Ação '{a['text'][:40]}'", a.get("evidence_ids", []))
    for t in draft.get("progress", []):
        for it in t["items"]:
            check(f"Progresso '{it['text'][:40]}'", it.get("evidence_ids", []))
    for im in draft.get("impediments", []):
        check(f"Impeditivo '{im['summary'][:40]}'", im.get("evidence_ids", []))
    for r in draft.get("risks", []):
        check(f"Risco '{r['text'][:40]}'", r.get("evidence_ids", []))
    return problems


def review_gate(ctx: Context, node_input: Critique):
    """Decide: publicar ou voltar ao redator. Valida a evidência EM CÓDIGO,
    mesmo que o crítico (LLM) tenha aprovado."""
    draft = ctx.state["report_draft_data"]
    revisions = int(ctx.state.get("revisions", 0))
    critique = node_input if isinstance(node_input, Critique) else Critique(**node_input)
    problems = list(critique.problems) if not critique.approved else []
    problems += _evidence_problems(draft, set(ctx.state["evidence_ids"]))

    if not problems:
        yield Event(route="publish", state={"incomplete_review": False})
    elif revisions + 1 >= MAX_REVISIONS:
        yield Event(route="publish", state={"incomplete_review": True})  # sai marcado como "revisão incompleta"
    else:
        yield Event(route="revise", output="Revise o report.", state={
            "revisions": revisions + 1,
            "critique_feedback": as_data("Problemas a corrigir:\n- " + "\n- ".join(problems)),
        })


# -------------------------------------------------------------------------- 4. publicação

def publish_report(ctx: Context):
    """Grava o report como NOVA versão (as anteriores ficam no histórico)."""
    team_id, member_id = str(ctx.state["team_id"]), int(ctx.state["member_id"])
    draft = ReportDraft(**ctx.state["report_draft_data"]).model_dump()
    content = {
        **draft,
        "participation": ctx.state["participation"],
        "people": ctx.state["people"],
        "evidence_labels": ctx.state["evidence_labels"],
    }
    with db_session() as db:
        team = db.get(Team, team_id)
        cycle = repo.get_or_create_cycle(db, team)
        report = Report(cycle_id=cycle.id, team_id=team_id, version=repo.next_report_version(db, cycle.id),
                        generated_by=member_id, content=content, prompt_version=PROMPT_VERSION,
                        incomplete_review=bool(ctx.state.get("incomplete_review", False)))
        db.add(report)
        db.flush()
        report_id = report.id
    yield Event(state={"report_id": report_id}, message="Report publicado.", output=report_id)
