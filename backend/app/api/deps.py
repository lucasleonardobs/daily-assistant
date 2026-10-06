"""Dependências do FastAPI: banco, usuário logado e checagem de papel por time."""
from collections.abc import Iterator

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import current_email
from app.db import repository as repo
from app.db.models import Member, Team
from app.db.session import db_session


def get_db() -> Iterator[Session]:
    with db_session() as session:
        yield session


def team_or_404(team_id: str, db: Session = Depends(get_db)) -> Team:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(404, "Time não encontrado.")
    return team


def member_of_team(team: Team = Depends(team_or_404), email: str = Depends(current_email),
                   db: Session = Depends(get_db)) -> Member:
    """Quem está logado, como membro deste time. 403 se não faz parte dele."""
    member = next((m for m in repo.memberships(db, email) if m.team_id == team.id), None)
    if member is None:
        raise HTTPException(403, "Você não faz parte deste time.")
    return member


def manager_of_team(member: Member = Depends(member_of_team)) -> Member:
    if member.role != "manager":
        raise HTTPException(403, "Apenas gestores do time.")
    return member
