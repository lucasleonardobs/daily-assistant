"""Acesso em produção: login com senha, convites de uso único, bloqueio, sessões e CSRF."""
import logging
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import invites, security
from app.bootstrap import bootstrap_if_empty, check_production_settings
from app.config import settings
from app.db import repository as repo
from app.db.models import Invite, Team, User
from app.db.session import db_session, init_db
from app.db.urls import async_url, is_postgres, sync_url
from app.main import app

SECRET = "x" * 40
PASSWORD = "uma-senha-bem-longa-42"
DIEGO, LUCAS = "diego.rocha@bv.com.br", "lucas.barros@bv.com.br"


def make_user(email, password=PASSWORD, must_change=False):
    with db_session() as db:
        db.add(User(email=email, password_hash=security.hash_password(password), must_change_password=must_change))


def new_client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


@pytest.fixture()
def prod(db, monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "secret_key", SECRET)
    make_user(DIEGO)
    make_user(LUCAS)
    return new_client()


def login(client, email=DIEGO, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ------------------------------------------------------------------ login

def test_forged_dev_header_is_ignored_in_production(prod):
    assert prod.get("/api/me", headers={"X-User-Email": LUCAS}).status_code == 401
    assert prod.get("/api/dev/users").status_code == 404


def test_login_opens_session_and_logout_closes_it(prod):
    r = login(prod)
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert prod.get("/api/me").json()["email"] == DIEGO
    prod.post("/api/auth/logout")
    assert prod.get("/api/me").status_code == 401


def test_wrong_password_and_unknown_email_look_identical(prod):
    wrong = login(prod, DIEGO, "senha-errada-123")
    unknown = login(prod, "ninguem@bv.com.br", PASSWORD)
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()  # nada revela quais e-mails existem


def test_account_locks_after_repeated_failures_even_for_the_right_password(prod):
    for _ in range(settings.max_failed_logins):
        assert login(prod, DIEGO, "errada-errada-1").status_code == 401
    assert login(prod, DIEGO, PASSWORD).status_code == 429
    with db_session() as db:  # passado o tempo, volta a funcionar
        db.get(User, DIEGO).locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert login(prod, DIEGO, PASSWORD).status_code == 200


def test_successful_login_resets_failure_counter(prod):
    login(prod, DIEGO, "errada-errada-1")
    login(prod, DIEGO, PASSWORD)
    with db_session() as db:
        assert db.get(User, DIEGO).failed_attempts == 0


def test_removed_member_cannot_log_in(prod):
    with db_session() as db:
        for m in repo.memberships(db, DIEGO):
            m.role, m.email = "removed", f"removed+{m.id}@invalid"
    assert login(prod).status_code == 401


def test_tampered_cookie_is_rejected(prod):
    login(prod)
    cookie = prod.cookies.get("daily_session")
    prod.cookies.set("daily_session", cookie[:-3] + "abc")
    assert prod.get("/api/me").status_code == 401


# ------------------------------------------------------------------ convites

def manager_invite(client, member_email=DIEGO):
    login(client, LUCAS)
    members = client.get("/api/teams/pagamentos").json()["members"]
    member_id = next(m["id"] for m in members if m["email"] == member_email)
    return client.post(f"/api/teams/pagamentos/members/{member_id}/invite")


def token_of(link: str) -> str:
    return link.split("token=")[1]


def test_invite_flow_sets_password_once(prod):
    r = manager_invite(prod)
    assert r.status_code == 200
    token = token_of(r.json()["link"])

    member = new_client()
    assert member.get(f"/api/auth/invite/{token}").json()["email"] == DIEGO
    weak = member.post("/api/auth/activate", json={"token": token, "password": "curta"})
    assert weak.status_code == 422
    ok = member.post("/api/auth/activate", json={"token": token, "password": "nova-senha-segura-77"})
    assert ok.status_code == 200 and member.get("/api/me").json()["email"] == DIEGO

    # uso único: o mesmo link não funciona de novo
    assert new_client().post("/api/auth/activate", json={"token": token, "password": "outra-senha-segura-88"}).status_code == 404
    assert new_client().get(f"/api/auth/invite/{token}").status_code == 404
    # e a senha nova é a que vale
    assert login(new_client(), DIEGO, "nova-senha-segura-77").status_code == 200
    assert login(new_client(), DIEGO, PASSWORD).status_code == 401


def test_invite_token_is_stored_only_as_a_hash(prod):
    token = token_of(manager_invite(prod).json()["link"])
    with db_session() as db:
        stored = [i.token_hash for i in db.query(Invite)]
    assert token not in stored and security.token_digest(token) in stored


def test_expired_invite_is_rejected(prod):
    token = token_of(manager_invite(prod).json()["link"])
    with db_session() as db:
        db.query(Invite).one().expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert new_client().post("/api/auth/activate", json={"token": token, "password": "nova-senha-segura-77"}).status_code == 404


def test_new_invite_revokes_the_previous_one(prod):
    first = token_of(manager_invite(prod).json()["link"])
    second = token_of(manager_invite(prod).json()["link"])
    assert new_client().get(f"/api/auth/invite/{first}").status_code == 404
    assert new_client().get(f"/api/auth/invite/{second}").status_code == 200


def test_reset_via_invite_ends_open_sessions(prod):
    old_session = new_client()
    login(old_session)
    assert old_session.get("/api/me").status_code == 200
    token = token_of(manager_invite(prod).json()["link"])
    new_client().post("/api/auth/activate", json={"token": token, "password": "nova-senha-segura-77"})
    assert old_session.get("/api/me").status_code == 401  # a sessão antiga caiu


def test_only_managers_of_the_team_can_create_invites(prod):
    login(prod)  # Diego é membro
    members = prod.get("/api/teams/pagamentos").json()["members"]
    anyone = members[0]["id"]
    assert prod.post(f"/api/teams/pagamentos/members/{anyone}/invite").status_code == 403


# ------------------------------------------------------------ troca de senha

def test_change_password_requires_current_and_ends_other_sessions(prod):
    laptop, phone = new_client(), new_client()
    login(laptop)
    login(phone)
    bad = laptop.post("/api/auth/change-password", json={"current_password": "errada-errada-1", "new_password": "outra-senha-forte-99"})
    assert bad.status_code == 401
    ok = laptop.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "outra-senha-forte-99"})
    assert ok.status_code == 200
    assert laptop.get("/api/me").status_code == 200   # a sessão atual continua
    assert phone.get("/api/me").status_code == 401    # as demais caem


def test_forced_password_change_blocks_everything_else(db, monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "secret_key", SECRET)
    make_user(DIEGO, must_change=True)
    client = new_client()
    assert login(client).json()["must_change_password"] is True
    assert client.get("/api/me").json()["must_change_password"] is True
    blocked = client.get("/api/teams/pagamentos")
    assert blocked.status_code == 403 and blocked.json()["detail"] == "password_change_required"
    client.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "senha-definitiva-123"})
    assert client.get("/api/teams/pagamentos").status_code == 200


# ----------------------------------------------------------------------- CSRF

def test_cross_site_write_with_session_cookie_is_refused(prod):
    login(prod)
    body = {"current_password": PASSWORD, "new_password": "outra-senha-forte-99"}
    evil = prod.post("/api/auth/change-password", json=body, headers={"Origin": "https://site-malicioso.com"})
    assert evil.status_code == 403
    same = prod.post("/api/auth/change-password", json=body, headers={"Origin": "https://testserver"})
    assert same.status_code == 200


# ------------------------------------------------------------------ bootstrap

def test_bootstrap_creates_team_and_logs_a_working_one_time_invite(tmp_path, monkeypatch, caplog):
    init_db(str(tmp_path / "empty.db"))
    monkeypatch.setattr(settings, "dev_mode", False)
    monkeypatch.setattr(settings, "secret_key", SECRET)
    monkeypatch.setattr(settings, "bootstrap_manager_email", "Gestor@Empresa.com")
    monkeypatch.setattr(settings, "bootstrap_team_name", "Squad Piloto")
    with caplog.at_level(logging.WARNING, logger="daily.bootstrap"):
        with db_session() as db:
            bootstrap_if_empty(db, base_url="https://app.exemplo.com")
        with db_session() as db:
            assert [t.id for t in db.query(Team)] == ["squad-piloto"]
    link = re.search(r"https://app\.exemplo\.com/ativar\?token=\S+", caplog.text).group(0)
    client = new_client()
    r = client.post("/api/auth/activate", json={"token": token_of(link), "password": "primeira-senha-forte-1"})
    assert r.status_code == 200 and client.get("/api/me").json()["email"] == "gestor@empresa.com"
    # com a senha definida, uma reinicialização não gera outro convite
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="daily.bootstrap"):
        with db_session() as db:
            bootstrap_if_empty(db, base_url="https://app.exemplo.com")
    assert "CONVITE" not in caplog.text


def test_production_refuses_weak_secret(monkeypatch):
    monkeypatch.setattr(settings, "secret_key", "dev-only-change-me")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        check_production_settings()


# ------------------------------------------------------------------ senhas e URLs

@pytest.mark.parametrize("password,expected", [
    ("curta", "pelo menos"), ("diego.rocha@bv.com.br123", "e-mail"), ("Diego.Rocha-2026!", "e-mail"),
    ("aaaaaaaaaaaa", "repetitiva"), ("x" * 200, "no máximo"), ("uma-senha-boa-de-verdade", None),
])
def test_password_policy(password, expected):
    problem = security.password_problem(password, DIEGO)
    assert (expected is None and problem is None) or (expected in (problem or ""))


def test_postgres_urls_are_normalized_for_each_driver():
    aiven = "postgres://avnadmin:pw@host.aivencloud.com:12345/defaultdb?sslmode=require"
    assert is_postgres(aiven) and not is_postgres("sqlite:///x.db") and not is_postgres(None)
    assert sync_url(aiven) == "postgresql+psycopg://avnadmin:pw@host.aivencloud.com:12345/defaultdb?sslmode=require"
    assert async_url(aiven) == "postgresql+asyncpg://avnadmin:pw@host.aivencloud.com:12345/defaultdb?ssl=require"
