from app.db import repository as repo
from app.db.models import Impediment
from app.domain.schemas import Blocker, CheckinDraft, PlannedItem


def _member(db, team, name):
    return next(m for m in repo.team_members(db, team) if m.name == name)


def test_seed_has_two_teams_and_open_impediments(db):
    assert len(repo.team_members(db, "pagamentos")) == 8  # 7 pessoas + gestor
    names = {m.id: m.name for m in repo.team_members(db, "pagamentos")}
    open_ = [repo.impediment_view(i, repo.today_for(db.get(repo.Team, "pagamentos")), names, 2)
             for i in repo.open_impediments(db, "pagamentos")]
    assert {i["reporter"] for i in open_} >= {"Ana Souza", "Diego Rocha"}
    assert any(i["aged"] for i in open_)


def test_cycle_is_created_once_per_day(db):
    team = db.get(repo.Team, "pagamentos")
    assert repo.get_or_create_cycle(db, team).id == repo.get_or_create_cycle(db, team).id


def test_save_checkin_creates_and_resolves_own_impediments(db):
    team = db.get(repo.Team, "pagamentos")
    cycle = repo.get_or_create_cycle(db, team)
    diego = _member(db, "pagamentos", "Diego Rocha")
    own = repo.open_impediments(db, "pagamentos", diego.id)[0]

    repo.save_checkin(db, cycle=cycle, member=diego, draft=CheckinDraft(
        planned=[PlannedItem(summary="Integrar login")],
        blockers=[Blocker(summary="Sem massa de dados", category="TECHNICAL", severity="LOW")],
        resolved_impediment_ids=[own.id]))
    db.flush()

    assert db.get(Impediment, own.id).status == "RESOLVED"
    assert any(i.summary == "Sem massa de dados" for i in repo.open_impediments(db, "pagamentos", diego.id))


def test_save_checkin_ignores_impediments_of_other_members(db):
    team = db.get(repo.Team, "pagamentos")
    cycle = repo.get_or_create_cycle(db, team)
    diego = _member(db, "pagamentos", "Diego Rocha")
    ana_imp = repo.open_impediments(db, "pagamentos", _member(db, "pagamentos", "Ana Souza").id)[0]

    repo.save_checkin(db, cycle=cycle, member=diego, draft=CheckinDraft(resolved_impediment_ids=[ana_imp.id]))
    db.flush()

    assert db.get(Impediment, ana_imp.id).status == "OPEN"


def test_editing_checkin_same_day_bumps_version(db):
    team = db.get(repo.Team, "pagamentos")
    cycle = repo.get_or_create_cycle(db, team)
    diego = _member(db, "pagamentos", "Diego Rocha")
    first = repo.save_checkin(db, cycle=cycle, member=diego, draft=CheckinDraft(notes="v1"))
    second = repo.save_checkin(db, cycle=cycle, member=diego, draft=CheckinDraft(notes="v2"))
    assert first.id == second.id and second.version == 2 and second.data["notes"] == "v2"


def test_confirmed_at_is_serialized_with_timezone(db):
    """SQLite devolve datas sem fuso; sem o sufixo, o navegador mostraria a hora errada."""
    team = db.get(repo.Team, "pagamentos")
    cycle = repo.get_or_create_cycle(db, team)
    repo.save_checkin(db, cycle=cycle, member=_member(db, "pagamentos", "Ana Souza"), draft=CheckinDraft())
    db.flush()
    row = next(r for r in repo.day_status(db, cycle) if r["name"] == "Ana Souza")
    assert row["confirmed_at"].endswith("+00:00")
