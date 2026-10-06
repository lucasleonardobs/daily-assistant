"""Identidade do usuário.

Produção: o IAP do Cloud Run autentica com conta Google e envia o e-mail no header
`X-Goog-Authenticated-User-Email` ("accounts.google.com:fulano@empresa.com").
Dev (DEV_MODE=true): aceita também `X-User-Email`, para trocar de usuário sem login.

Só o e-mail vem do header. Papel e time são resolvidos no banco (tabela members).
"""
from fastapi import HTTPException, Request

from app.config import settings


def current_email(request: Request) -> str:
    email = request.headers.get("x-user-email") if settings.dev_mode else None
    if not email:
        iap = request.headers.get("x-goog-authenticated-user-email", "")
        email = iap.split(":")[-1] if iap else None
    if not email:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    return email.strip().lower()
