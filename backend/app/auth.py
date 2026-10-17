"""Identidade do usuário.

Produção (DEV_MODE=false): login com e-mail e senha (app/api/auth.py) que abre um cookie de sessão
assinado com SECRET_KEY. O cookie guarda o e-mail e a versão da credencial; a cada requisição o banco
confirma que a versão ainda vale (trocar a senha derruba as sessões antigas). Papel e time são sempre
resolvidos no banco, nunca no cookie.
Dev (DEV_MODE=true): aceita também o header `X-User-Email`, para trocar de usuário sem login.

Nenhum header de proxy é confiado: num host público qualquer cliente poderia forjá-lo.
"""
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import settings
from app.db.models import User
from app.db.session import db_session

COOKIE = "daily_session"
PASSWORD_CHANGE_REQUIRED = "password_change_required"
# Enquanto a troca de senha é obrigatória, só estas rotas funcionam.
_ALLOWED_WHILE_CHANGING = {"/api/me", "/api/auth/change-password", "/api/auth/logout"}


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="daily-session")


def make_session_token(email: str, version: int) -> str:
    return _serializer().dumps({"email": email.lower(), "v": version})


def read_session_token(token: str | None) -> tuple[str, int] | None:
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=settings.session_hours * 3600)
        return data["email"], int(data["v"])
    except (BadSignature, KeyError, TypeError, ValueError):  # inclui expirado
        return None


def current_email(request: Request) -> str:
    if settings.dev_mode and request.headers.get("x-user-email"):
        return request.headers["x-user-email"].strip().lower()
    session = read_session_token(request.cookies.get(COOKIE))
    if session is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    email, version = session
    with db_session() as db:
        user = db.get(User, email)
        if user is None or user.token_version != version:
            raise HTTPException(status_code=401, detail="Sessão encerrada. Entre novamente.")
        if user.must_change_password and request.url.path not in _ALLOWED_WHILE_CHANGING:
            raise HTTPException(status_code=403, detail=PASSWORD_CHANGE_REQUIRED)
    return email
