"""Tabelas do produto (SQLite no MVP). Todo dado é particionado por team_id."""
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # slug, ex.: "pagamentos"
    name: Mapped[str] = mapped_column(String)
    timezone: Mapped[str] = mapped_column(String, default="America/Sao_Paulo")
    cutoff_time: Mapped[str] = mapped_column(String, default="10:00")
    base_questions: Mapped[list] = mapped_column(JSON, default=list)


class Member(Base):
    """Uma pessoa em um time. A mesma pessoa em dois times são duas linhas."""

    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("team_id", "email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String, default="member")  # "member" | "manager"


class StandupCycle(Base):
    """O dia de um time. Criado no primeiro acesso do dia (sem agendador)."""

    __tablename__ = "standup_cycles"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # "{team_id}_{date}"
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    day: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, default="OPEN")


class Checkin(Base):
    """Check-in confirmado. Uma linha por pessoa por dia; editar incrementa a versão."""

    __tablename__ = "checkins"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # "{cycle_id}_{member_id}"
    cycle_id: Mapped[str] = mapped_column(ForeignKey("standup_cycles.id"))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    day: Mapped[date] = mapped_column(Date)
    data: Mapped[dict] = mapped_column(JSON)  # CheckinDraft serializado
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Impediment(Base):
    """Ciclo de vida: OPEN → RESOLVED."""

    __tablename__ = "impediments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    checkin_id: Mapped[str] = mapped_column(ForeignKey("checkins.id"))  # origem (evidência)
    summary: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String, default="OTHER")
    severity: Mapped[str] = mapped_column(String, default="MEDIUM")
    needs_from: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="OPEN", index=True)
    opened_on: Mapped[date] = mapped_column(Date)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class Report(Base):
    """Cada clique em Gerar report cria uma nova versão; as anteriores ficam."""

    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("cycle_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_id: Mapped[str] = mapped_column(ForeignKey("standup_cycles.id"))
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    version: Mapped[int] = mapped_column(Integer)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    generated_by: Mapped[int] = mapped_column(ForeignKey("members.id"))
    content: Mapped[dict] = mapped_column(JSON)  # ReportContent serializado
    prompt_version: Mapped[str] = mapped_column(String)
    incomplete_review: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback: Mapped[dict] = mapped_column(JSON, default=dict)  # {"a1": "useful" | "not_useful"}
