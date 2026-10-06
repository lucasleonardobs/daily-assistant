"""Leitura e gravação no SQLite. É o único lugar que conhece as tabelas.

Usado pela API e pelos nós de código dos agentes. Os LLMs nunca falam com o banco.
"""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Checkin, Impediment, Member, Report, StandupCycle, Team, utcnow
from app.domain import rules
from app.domain.schemas import CheckinDraft

DEFAULT_QUESTIONS = [
    "O que avançou desde o último check-in?",
    "O que entra hoje?",
    "Algo está bloqueando você?",
]


# ------------------------------------------------------------ times e membros

def today_for(team: Team) -> date:
    return datetime.now(ZoneInfo(team.timezone)).date()


def memberships(db: Session, email: str) -> list[Member]:
    return list(db.scalars(select(Member).where(Member.email == email.lower())))


def team_members(db: Session, team_id: str) -> list[Member]:
    return list(db.scalars(select(Member).where(Member.team_id == team_id, Member.role != "removed")
                           .order_by(Member.name)))


def create_team(db: Session, *, team_id: str, name: str, timezone_: str, cutoff: str,
                questions: list[str] | None, creator_name: str, creator_email: str) -> Team:
    team = Team(id=team_id, name=name, timezone=timezone_, cutoff_time=cutoff,
                base_questions=questions or DEFAULT_QUESTIONS)
    db.add(team)
    db.flush()  # time antes do membro (sem relationship(), a ordem não é automática)
    db.add(Member(team_id=team_id, name=creator_name, email=creator_email.lower(), role="manager"))
    db.flush()
    return team


# ------------------------------------------------------------------- ciclo

def get_or_create_cycle(db: Session, team: Team, day: date | None = None) -> StandupCycle:
    day = day or today_for(team)
    cycle_id = f"{team.id}_{day.isoformat()}"
    cycle = db.get(StandupCycle, cycle_id)
    if cycle is None:
        cycle = StandupCycle(id=cycle_id, team_id=team.id, day=day)
        db.add(cycle)
        db.flush()
    return cycle


def day_status(db: Session, cycle: StandupCycle) -> list[dict]:
    """Quem respondeu e quem está pendente no dia (painel do gestor)."""
    checkins = {c.member_id: c for c in db.scalars(select(Checkin).where(Checkin.cycle_id == cycle.id))}
    rows = []
    for m in team_members(db, cycle.team_id):
        c = checkins.get(m.id)
        if m.role == "manager" and c is None:
            continue  # gestor só entra na lista de participação se também fez check-in
        rows.append({"member_id": m.id, "name": m.name, "email": m.email, "role": m.role,
                     "responded": c is not None,
                     "confirmed_at": utc_iso(c.confirmed_at) if c else None,
                     "checkin_id": c.id if c else None})
    return rows


# --------------------------------------------------------------- check-ins

def checkins_of_day(db: Session, team_id: str, day: date) -> list[Checkin]:
    return list(db.scalars(select(Checkin).where(Checkin.team_id == team_id, Checkin.day == day)))


def last_checkin_before(db: Session, member_id: int, day: date) -> Checkin | None:
    return db.scalars(
        select(Checkin).where(Checkin.member_id == member_id, Checkin.day < day)
        .order_by(Checkin.day.desc()).limit(1)
    ).first()


def recent_checkins(db: Session, member_id: int, before: date, limit: int = 4) -> list[Checkin]:
    return list(db.scalars(
        select(Checkin).where(Checkin.member_id == member_id, Checkin.day < before)
        .order_by(Checkin.day.desc()).limit(limit)
    ))


def save_checkin(db: Session, *, cycle: StandupCycle, member: Member, draft: CheckinDraft) -> Checkin:
    """Grava o check-in confirmado, cria impeditivos novos e resolve os destravados.

    Só resolve/atualiza impeditivos que pertencem a este membro, mesmo que o modelo
    cite outro id.
    """
    checkin_id = f"{cycle.id}_{member.id}"
    checkin = db.get(Checkin, checkin_id)
    data = draft.model_dump()
    if checkin is None:
        checkin = Checkin(id=checkin_id, cycle_id=cycle.id, team_id=cycle.team_id,
                          member_id=member.id, day=cycle.day, data=data)
        db.add(checkin)
    else:  # edição no mesmo dia: a nova versão substitui a anterior
        checkin.data, checkin.version, checkin.confirmed_at = data, checkin.version + 1, utcnow()
    db.flush()

    own_open = {i.id: i for i in db.scalars(select(Impediment).where(
        Impediment.member_id == member.id, Impediment.status == "OPEN"))}

    for imp_id in draft.resolved_impediment_ids:
        imp = own_open.get(imp_id)
        if imp:
            imp.status, imp.resolved_at = "RESOLVED", utcnow()
            imp.note = imp.note or "Resolvido no check-in"

    for b in draft.blockers:
        existing = own_open.get(b.existing_impediment_id) if b.existing_impediment_id else None
        if existing and existing.status == "OPEN":
            existing.summary, existing.severity, existing.category = b.summary, b.severity, b.category
            existing.needs_from = b.needs_from or existing.needs_from
        else:
            db.add(Impediment(team_id=cycle.team_id, member_id=member.id, checkin_id=checkin.id,
                              summary=b.summary, category=b.category, severity=b.severity,
                              needs_from=b.needs_from, opened_on=cycle.day))
    db.flush()
    return checkin


# -------------------------------------------------------------- impeditivos

def open_impediments(db: Session, team_id: str, member_id: int | None = None) -> list[Impediment]:
    q = select(Impediment).where(Impediment.team_id == team_id, Impediment.status == "OPEN")
    if member_id is not None:
        q = q.where(Impediment.member_id == member_id)
    return list(db.scalars(q.order_by(Impediment.opened_on)))


def impediment_view(imp: Impediment, today: date, names: dict[int, str], threshold: int) -> dict:
    age = rules.business_days_between(imp.opened_on, today)
    return {"id": imp.id, "summary": imp.summary, "category": imp.category, "severity": imp.severity,
            "needs_from": imp.needs_from, "reporter": names.get(imp.member_id, "?"),
            "member_id": imp.member_id, "status": imp.status, "age_days": age,
            "age_label": rules.age_label(age), "aged": rules.is_aged(age, threshold),
            "note": imp.note, "checkin_id": imp.checkin_id}


# ------------------------------------------------------------------ reports

def next_report_version(db: Session, cycle_id: str) -> int:
    last = db.scalars(select(Report.version).where(Report.cycle_id == cycle_id)
                      .order_by(Report.version.desc()).limit(1)).first()
    return (last or 0) + 1


def reports_of_cycle(db: Session, cycle_id: str) -> list[Report]:
    return list(db.scalars(select(Report).where(Report.cycle_id == cycle_id).order_by(Report.version)))


def utc_iso(dt: datetime) -> str:
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()
