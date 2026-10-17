"""Primeiro acesso em produção: sem seed, cria o primeiro time e gestor e registra um link de convite no log."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import invites
from app.config import settings
from app.db import repository as repo
from app.db.models import Team, User

log = logging.getLogger("daily.bootstrap")


def check_production_settings() -> None:
    """Recusa subir em produção com configuração insegura."""
    if settings.secret_key == "dev-only-change-me" or len(settings.secret_key) < 32:
        raise RuntimeError("Configuração de produção inválida: SECRET_KEY precisa ter 32+ caracteres e não pode ser o valor padrão")


def bootstrap_if_empty(db: Session, base_url: str | None = None) -> None:
    """Cria o primeiro time/gestor (banco vazio) e garante um convite para ele definir a senha.

    O link vai para o log (uso único, expira em INVITE_HOURS). Se o gestor ainda não tiver senha numa
    reinicialização posterior, um novo link é gerado: serve de recuperação do primeiro acesso.
    """
    email = (settings.bootstrap_manager_email or "").strip().lower()
    if not email:
        return
    if not db.scalars(select(Team)).first():
        team = repo.create_team(
            db, team_id=repo.slugify(settings.bootstrap_team_name), name=settings.bootstrap_team_name,
            timezone_="America/Sao_Paulo", cutoff="10:00", questions=None,
            creator_name=settings.bootstrap_manager_name, creator_email=email)
        log.info("Primeiro time criado: %s", team.name)
    if db.get(User, email) is None and repo.memberships(db, email):
        token, expires = invites.create_invite(db, email, created_by="sistema")
        link = invites.invite_link(base_url or f"https://{_public_domain()}", token)
        log.warning("CONVITE DO PRIMEIRO GESTOR (uso unico, expira em %s): %s", expires.strftime("%d/%m %H:%M UTC"), link)


def _public_domain() -> str:
    import os
    return os.environ.get("RAILWAY_PUBLIC_DOMAIN", "localhost:8000")
