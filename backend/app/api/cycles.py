"""O dia do time: quem respondeu e impeditivos abertos (painel do gestor)."""
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, member_of_team, team_or_404
from app.config import settings
from app.db import repository as repo
from app.db.models import Impediment, Member, Team

router = APIRouter(prefix="/api/teams/{team_id}/cycles", tags=["cycles"])


@router.get("/today")
def today(team: Team = Depends(team_or_404), me: Member = Depends(member_of_team), db: Session = Depends(get_db)):
    cycle = repo.get_or_create_cycle(db, team)  # F1: o ciclo nasce no primeiro acesso do dia
    status = repo.day_status(db, cycle)
    latest = repo.reports_of_cycle(db, cycle.id)
    out = {
        "cycle_id": cycle.id, "date": cycle.day.isoformat(),
        "team": {"id": team.id, "name": team.name, "timezone": team.timezone, "cutoff_time": team.cutoff_time},
        "responded": sum(1 for s in status if s["responded"]), "total": len(status),
        "latest_report_id": latest[-1].id if latest else None,
    }
    if me.role != "manager":  # membro vê só os totais; a lista nominal é do gestor
        return out

    names = {s["member_id"]: s["name"] for s in status}
    names.update({m.id: m.name for m in repo.team_members(db, team.id)})
    out["members"] = status
    out["impediments"] = sorted(
        (repo.impediment_view(i, cycle.day, names, settings.aged_threshold_days)
         for i in repo.open_impediments(db, team.id)), key=lambda i: -i["age_days"])
    tz = ZoneInfo(team.timezone)
    out["resolved_today"] = [
        {"id": i.id, "summary": i.summary, "note": i.note}
        for i in db.scalars(select(Impediment).where(Impediment.team_id == team.id, Impediment.status == "RESOLVED"))
        if i.resolved_at and repo.as_utc(i.resolved_at).astimezone(tz).date() == cycle.day]
    out["aged_threshold_days"] = settings.aged_threshold_days
    return out
