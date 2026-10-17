"""Quem está logado e a quais times pertence."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth import current_email
from app.config import settings
from app.db import repository as repo
from app.db.models import Member, Team, User

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me")
def me(email: str = Depends(current_email), db: Session = Depends(get_db)):
    memberships = repo.memberships(db, email)
    if not memberships:  # só e-mails cadastrados em members entram
        raise HTTPException(403, "Seu e-mail não está cadastrado em nenhum time.")
    teams = {t.id: t for t in db.scalars(select(Team).where(Team.id.in_([m.team_id for m in memberships])))}
    return {
        "email": email, "name": memberships[0].name, "dev_mode": settings.dev_mode,
        "must_change_password": bool((u := db.get(User, email)) and u.must_change_password),
        "memberships": [{"member_id": m.id, "team_id": m.team_id, "team_name": teams[m.team_id].name,
                         "role": m.role, "name": m.name} for m in memberships],
    }


@router.get("/dev/users")
def dev_users(db: Session = Depends(get_db)):
    """Lista de usuários para o seletor de dev. Não existe fora do DEV_MODE."""
    if not settings.dev_mode:
        raise HTTPException(404)
    rows = db.scalars(select(Member).order_by(Member.name)).all()
    seen: dict[str, dict] = {}
    for m in rows:
        seen.setdefault(m.email, {"email": m.email, "name": m.name, "roles": []})["roles"].append(m.role)
    return list(seen.values())
