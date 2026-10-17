"""Login com e-mail e senha, ativação por convite e troca de senha."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import invites, security
from app.api.deps import get_db
from app.auth import COOKIE, current_email, make_session_token
from app.config import settings
from app.db import repository as repo
from app.db.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

INVALID_LOGIN = "E-mail ou senha inválidos."  # a mesma mensagem para e-mail inexistente e senha errada


class LoginIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=security.MAX_PASSWORD_LENGTH)


class ActivateIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=security.MAX_PASSWORD_LENGTH)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=security.MAX_PASSWORD_LENGTH)
    new_password: str = Field(max_length=security.MAX_PASSWORD_LENGTH)


def _open_session(response: Response, user: User) -> None:
    response.set_cookie(COOKIE, make_session_token(user.email, user.token_version),
                        max_age=settings.session_hours * 3600, httponly=True, samesite="lax",
                        secure=settings.cookie_secure, path="/")


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/config")
def config():
    """O que a tela de login precisa saber (nada secreto)."""
    return {"dev_mode": settings.dev_mode}


@router.post("/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user = db.get(User, email)
    now = datetime.now(timezone.utc)

    if user and user.locked_until and _utc(user.locked_until) > now:
        raise HTTPException(429, f"Muitas tentativas. Tente novamente em {settings.lockout_minutes} minutos.")

    # Só entra quem tem senha E ainda pertence a algum time (membro removido perde o acesso).
    valid = security.verify_password(body.password, user.password_hash if user else None)
    if not (valid and repo.memberships(db, email)):
        if user:
            user.failed_attempts += 1
            if user.failed_attempts >= settings.max_failed_logins:
                user.locked_until, user.failed_attempts = now + timedelta(minutes=settings.lockout_minutes), 0
            db.commit()  # grava a falha antes de responder com erro (o get_db desfaz tudo ao levantar exceção)
        raise HTTPException(401, INVALID_LOGIN)

    user.failed_attempts, user.locked_until, user.last_login_at = 0, None, now
    if security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(body.password)
    _open_session(response, user)
    return {"email": email, "must_change_password": user.must_change_password}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/invite/{token}")
def check_invite(token: str, db: Session = Depends(get_db)):
    """A tela de ativação mostra para quem é o convite antes de pedir a senha."""
    invite = invites.find_valid_invite(db, token)
    members = repo.memberships(db, invite.email) if invite else []
    if not members:
        raise HTTPException(404, "Convite inválido ou expirado. Peça um novo link ao seu gestor.")
    return {"email": invite.email, "name": members[0].name}


@router.post("/activate")
def activate(body: ActivateIn, response: Response, db: Session = Depends(get_db)):
    """Define a senha a partir de um convite de uso único (primeiro acesso ou redefinição)."""
    invite = invites.find_valid_invite(db, body.token)
    if invite is None or not repo.memberships(db, invite.email):
        raise HTTPException(404, "Convite inválido ou expirado. Peça um novo link ao seu gestor.")
    problem = security.password_problem(body.password, invite.email)
    if problem:
        raise HTTPException(422, problem)

    user = db.get(User, invite.email)
    if user is None:
        user = User(email=invite.email, password_hash=security.hash_password(body.password))
        db.add(user)
    else:  # redefinição: troca a senha e derruba as sessões abertas
        user.password_hash = security.hash_password(body.password)
        user.token_version += 1
    user.must_change_password, user.failed_attempts, user.locked_until = False, 0, None
    user.last_login_at = datetime.now(timezone.utc)
    invite.used_at = datetime.now(timezone.utc)
    db.flush()
    _open_session(response, user)
    return {"email": user.email}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, response: Response, email: str = Depends(current_email),
                    db: Session = Depends(get_db)):
    user = db.get(User, email)
    if user is None or not security.verify_password(body.current_password, user.password_hash):
        raise HTTPException(401, "A senha atual está incorreta.")
    problem = security.password_problem(body.new_password, email)
    if problem:
        raise HTTPException(422, problem)
    if body.new_password == body.current_password:
        raise HTTPException(422, "A nova senha precisa ser diferente da atual.")
    user.password_hash = security.hash_password(body.new_password)
    user.token_version += 1  # as outras sessões deste usuário deixam de valer
    user.must_change_password = False
    db.flush()
    _open_session(response, user)
    return {"ok": True}
