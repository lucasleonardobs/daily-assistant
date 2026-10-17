"""Convites: link de uso único para definir (ou redefinir) a senha. Substitui o e-mail de "esqueci a senha"."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Invite
from app.security import new_token, token_digest


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite devolve datas sem fuso


def create_invite(db: Session, email: str, created_by: str) -> tuple[str, datetime]:
    """Gera um convite novo e invalida os anteriores ainda abertos desse e-mail."""
    email = email.lower()
    now = datetime.now(timezone.utc)
    for old in db.scalars(select(Invite).where(Invite.email == email, Invite.used_at.is_(None))):
        old.used_at = now
    token = new_token()
    expires = now + timedelta(hours=settings.invite_hours)
    db.add(Invite(token_hash=token_digest(token), email=email, created_by=created_by.lower(), expires_at=expires))
    db.flush()
    return token, expires


def find_valid_invite(db: Session, token: str) -> Invite | None:
    invite = db.scalars(select(Invite).where(Invite.token_hash == token_digest(token))).first()
    if invite is None or invite.used_at is not None or _utc(invite.expires_at) < datetime.now(timezone.utc):
        return None
    return invite


def invite_link(base_url: str, token: str) -> str:
    return f"{(settings.public_base_url or base_url).rstrip('/')}/ativar?token={token}"
