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


def test_get_or_create_cycle_survives_concurrent_first_access(db):
    """Regressão: painel e check-in pedem o ciclo do dia ao mesmo tempo; o segundo não pode estourar."""
    import threading
    from datetime import date

    from app.db.session import db_session

    team = db.get(repo.Team, "pagamentos")
    day, errors, ids = date(2030, 1, 7), [], []
    barrier = threading.Barrier(6)

    def worker():
        try:
            barrier.wait()
            with db_session() as s:
                ids.append(repo.get_or_create_cycle(s, s.get(repo.Team, team.id), day).id)
        except Exception as e:  # noqa: BLE001
            errors.append(repr(e))

    threads = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors
    assert set(ids) == {"pagamentos_2030-01-07"} and len(ids) == 6


def test_naive_sqlite_datetimes_are_read_as_utc_not_local_time():
    """Regressão: 01:16 UTC do dia 7 ainda é dia 6 em São Paulo. Não pode depender do relógio da máquina."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    naive_utc = datetime(2026, 10, 7, 1, 16)  # como o SQLite devolve
    assert repo.as_utc(naive_utc).astimezone(ZoneInfo("America/Sao_Paulo")).date().isoformat() == "2026-10-06"
    assert repo.as_utc(naive_utc).isoformat().endswith("+00:00")


def test_gemini_3_keeps_default_temperature_but_older_models_do_not():
    """Regressão: o Google recomenda não baixar a temperatura nos modelos Gemini 3."""
    from agents.shared.models import generation_config

    assert generation_config(0.0, model="gemini-3.1-flash-lite").temperature is None
    assert generation_config(0.4, model="gemini-2.5-flash").temperature == 0.4
    assert generation_config(0.4, model=object()).temperature == 0.4  # modelos injetados (testes) mantêm
    assert generation_config(0.0, model="gemini-3.1-flash-lite").safety_settings  # filtros continuam ligados
