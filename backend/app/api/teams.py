"""Times e membros. Só gestores do time alteram."""
import re
import unicodedata
from zoneinfo import ZoneInfo, available_timezones

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, manager_of_team, member_of_team, team_or_404
from app.auth import current_email
from app.db import repository as repo
from app.db.models import Member, Team

router = APIRouter(prefix="/api/teams", tags=["teams"])


class TeamIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    timezone: str = "America/Sao_Paulo"
    cutoff_time: str = Field(default="10:00", pattern=r"^\d{2}:\d{2}$")
    base_questions: list[str] = Field(default_factory=list, max_length=6)


class MemberIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: str = Field(default="member", pattern="^(member|manager)$")


def _team_dict(team: Team, members: list[Member]) -> dict:
    return {"id": team.id, "name": team.name, "timezone": team.timezone, "cutoff_time": team.cutoff_time,
            "base_questions": team.base_questions,
            "members": [{"id": m.id, "name": m.name, "email": m.email, "role": m.role} for m in members]}


def _check_tz(tz: str) -> None:
    if tz not in available_timezones():
        raise HTTPException(422, "Fuso horário inválido.")


@router.post("", status_code=201)
def create_team(body: TeamIn, email: str = Depends(current_email), db: Session = Depends(get_db)):
    mine = repo.memberships(db, email)
    if not any(m.role == "manager" for m in mine):
        raise HTTPException(403, "Apenas gestores criam times.")
    _check_tz(body.timezone)
    slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFD", body.name.lower())
                  .encode("ascii", "ignore").decode()).strip("-") or "time"
    if db.get(Team, slug):
        raise HTTPException(409, "Já existe um time com esse nome.")
    team = repo.create_team(db, team_id=slug, name=body.name, timezone_=body.timezone, cutoff=body.cutoff_time,
                            questions=body.base_questions, creator_name=mine[0].name, creator_email=email)
    return _team_dict(team, repo.team_members(db, team.id))


@router.get("/{team_id}")
def get_team(team: Team = Depends(team_or_404), _: Member = Depends(member_of_team), db: Session = Depends(get_db)):
    return _team_dict(team, repo.team_members(db, team.id))


@router.put("/{team_id}")
def update_team(body: TeamIn, team: Team = Depends(team_or_404), _: Member = Depends(manager_of_team),
                db: Session = Depends(get_db)):
    _check_tz(body.timezone)
    team.name, team.timezone, team.cutoff_time = body.name, body.timezone, body.cutoff_time
    team.base_questions = [q.strip() for q in body.base_questions if q.strip()] or repo.DEFAULT_QUESTIONS
    return _team_dict(team, repo.team_members(db, team.id))


@router.post("/{team_id}/members", status_code=201)
def add_member(body: MemberIn, team: Team = Depends(team_or_404), _: Member = Depends(manager_of_team),
               db: Session = Depends(get_db)):
    email = body.email.lower()
    if any(m.email == email for m in repo.team_members(db, team.id)):
        raise HTTPException(409, "Essa pessoa já está no time.")
    db.add(Member(team_id=team.id, name=body.name, email=email, role=body.role))
    db.flush()
    return _team_dict(team, repo.team_members(db, team.id))


@router.delete("/{team_id}/members/{member_id}")
def remove_member(member_id: int, team: Team = Depends(team_or_404), me: Member = Depends(manager_of_team),
                  db: Session = Depends(get_db)):
    target = db.get(Member, member_id)
    if target is None or target.team_id != team.id:
        raise HTTPException(404, "Membro não encontrado.")
    managers = [m for m in repo.team_members(db, team.id) if m.role == "manager"]
    if target.role == "manager" and len(managers) == 1:
        raise HTTPException(409, "O time precisa de ao menos um gestor.")
    # O histórico (check-ins, impeditivos) fica: a pessoa só deixa de ter acesso.
    target.role = "removed"
    target.email = f"removed+{target.id}@invalid"
    return _team_dict(team, [m for m in repo.team_members(db, team.id) if m.role != "removed"])
