"""Report diário e impeditivos (ações do gestor)."""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import agent_runner
from app.api.deps import get_db, manager_of_team, member_of_team, team_or_404
from app.auth import current_email
from app.config import settings
from app.db import repository as repo
from app.db.models import Impediment, Member, Report, Team, utcnow

router = APIRouter(prefix="/api", tags=["reports"])


def _version_row(r: Report) -> dict:
    return {"id": r.id, "version": r.version, "generated_at": repo.utc_iso(r.generated_at),
            "responded": len(r.content.get("people", [])), "incomplete_review": r.incomplete_review}


@router.get("/teams/{team_id}/reports")
def list_versions(team: Team = Depends(team_or_404), _: Member = Depends(member_of_team),
                  db: Session = Depends(get_db)):
    """Versões do report de hoje (cada geração é uma nova versão)."""
    cycle = repo.get_or_create_cycle(db, team)
    return [_version_row(r) for r in repo.reports_of_cycle(db, cycle.id)]


@router.post("/teams/{team_id}/reports")
async def generate(team: Team = Depends(team_or_404), me: Member = Depends(manager_of_team),
                   db: Session = Depends(get_db)):
    """Roda o grafo do report. Responde em SSE com a etapa atual e, no fim, o id do report."""
    cycle = repo.get_or_create_cycle(db, team)
    if len(repo.reports_of_cycle(db, cycle.id)) >= settings.max_reports_per_day:  # cada geração custa várias chamadas
        raise HTTPException(429, f"Limite de {settings.max_reports_per_day} reports por dia atingido para este time.")
    if agent_runner.report_in_progress(team.id):
        raise HTTPException(409, "Já existe um report sendo gerado para este time.")
    db.commit()

    async def sse():
        async for event in agent_runner.stream_report(me):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _report_for(report_id: int, email: str, db: Session) -> Report:
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(404, "Report não encontrado.")
    if not any(m.team_id == report.team_id for m in repo.memberships(db, email)):
        raise HTTPException(403, "Você não faz parte deste time.")
    return report


@router.get("/reports/{report_id}")
def get_report(report_id: int, email: str = Depends(current_email), db: Session = Depends(get_db)):
    r = _report_for(report_id, email, db)
    return {**_version_row(r), "content": r.content, "feedback": r.feedback, "prompt_version": r.prompt_version}


class FeedbackIn(BaseModel):
    action_index: int = Field(ge=0, le=20)
    value: str | None = Field(pattern="^(useful|not_useful)$")  # None desmarca


@router.post("/reports/{report_id}/feedback")
def feedback(report_id: int, body: FeedbackIn, email: str = Depends(current_email), db: Session = Depends(get_db)):
    r = _report_for(report_id, email, db)
    me = next(m for m in repo.memberships(db, email) if m.team_id == r.team_id)
    if me.role != "manager":
        raise HTTPException(403, "Apenas gestores do time.")
    fb = dict(r.feedback or {})
    if body.value is None:
        fb.pop(str(body.action_index), None)
    else:
        fb[str(body.action_index)] = body.value
    r.feedback = fb  # reatribui para o SQLAlchemy perceber a mudança no JSON
    return {"feedback": fb}


class ImpedimentPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^RESOLVED$")
    note: str | None = Field(default=None, max_length=500)
    severity: str | None = Field(default=None, pattern="^(LOW|MEDIUM|HIGH)$")


@router.patch("/impediments/{impediment_id}")
def patch_impediment(impediment_id: int, body: ImpedimentPatch, email: str = Depends(current_email),
                     db: Session = Depends(get_db)):
    imp = db.get(Impediment, impediment_id)
    if imp is None:
        raise HTTPException(404, "Impeditivo não encontrado.")
    me = next((m for m in repo.memberships(db, email) if m.team_id == imp.team_id), None)
    if me is None or me.role != "manager":
        raise HTTPException(403, "Apenas gestores do time.")
    if body.severity:
        imp.severity = body.severity
    if body.status == "RESOLVED" and imp.status == "OPEN":
        imp.status, imp.resolved_at, imp.note = "RESOLVED", utcnow(), body.note or ""
    return {"id": imp.id, "status": imp.status, "severity": imp.severity, "note": imp.note}
