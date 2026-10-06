"""Dados de exemplo (os mesmos do protótipo) para desenvolvimento e demonstração.

Rodar: `uv run python -m app.seed`. É idempotente: não faz nada se já existir time.
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import repository as repo
from app.db.models import Checkin, Impediment, Member, Team
from app.db.session import db_session, init_db
from app.domain import rules
from app.domain.schemas import Blocker, CheckinDraft, DoneItem, PlannedItem

PAGAMENTOS = ["Ana Souza", "Bruno Lima", "Carla Mendes", "Diego Rocha",
              "Elisa Prado", "Felipe Nunes", "Gabriela Torres"]


def _email(name: str) -> str:
    import unicodedata
    plain = unicodedata.normalize("NFD", name.lower()).encode("ascii", "ignore").decode()
    return plain.replace(" ", ".") + "@bv.com.br"


def _back(day: date, n: int) -> date:
    for _ in range(n):
        day = rules.previous_business_day(day)
    return day


def _history(db: Session, team: Team, member: Member, day: date, draft: CheckinDraft) -> Checkin:
    cycle = repo.get_or_create_cycle(db, team, day)
    return repo.save_checkin(db, cycle=cycle, member=member, draft=draft)


def seed(db: Session) -> None:
    if db.scalars(select(Team)).first():
        return

    pag = Team(id="pagamentos", name="Squad Pagamentos", base_questions=repo.DEFAULT_QUESTIONS)
    onb = Team(id="onboarding", name="Squad Onboarding", base_questions=repo.DEFAULT_QUESTIONS)
    db.add_all([pag, onb])
    db.flush()  # sem relationship(), o SQLAlchemy não ordena inserts: times antes dos membros
    db.add(Member(team_id="pagamentos", name="Lucas Barros", email="lucas.barros@bv.com.br", role="manager"))
    db.add(Member(team_id="onboarding", name="Lucas Barros", email="lucas.barros@bv.com.br", role="manager"))
    for name in PAGAMENTOS:
        db.add(Member(team_id="pagamentos", name=name, email=_email(name)))
    for name in ["Helena Costa", "Igor Ramos"]:
        db.add(Member(team_id="onboarding", name=name, email=_email(name)))
    db.flush()

    by_name = {m.name: m for m in repo.team_members(db, "pagamentos")}
    today = repo.today_for(pag)
    d1, d3 = _back(today, 1), _back(today, 3)

    # Há 3 dias úteis: Ana ficou sem acesso ao staging e Diego sem homologação.
    _history(db, pag, by_name["Ana Souza"], d3, CheckinDraft(
        done=[DoneItem(summary="Mapeou o fluxo de estorno", related_to_previous_plan=False)],
        planned=[PlannedItem(summary="Testar estorno em staging")],
        blockers=[Blocker(summary="Sem acesso ao ambiente de staging", category="ACCESS",
                          severity="HIGH", needs_from="time de infraestrutura")]))
    _history(db, pag, by_name["Diego Rocha"], d3, CheckinDraft(
        done=[DoneItem(summary="Começou a tela de login", related_to_previous_plan=False)],
        planned=[PlannedItem(summary="Finalizar a tela de login")],
        blockers=[Blocker(summary="Ambiente de homologação fora do ar", category="ENVIRONMENT",
                          severity="HIGH", needs_from="time de infraestrutura")]))

    # Ontem: o plano que o agente vai citar na abertura do check-in de hoje.
    _history(db, pag, by_name["Diego Rocha"], d1, CheckinDraft(
        planned=[PlannedItem(summary="Finalizar a tela de login")],
        blockers=[Blocker(summary="Ambiente de homologação fora do ar", category="ENVIRONMENT",
                          severity="HIGH", needs_from="time de infraestrutura", existing_impediment_id=2)]))
    _history(db, pag, by_name["Carla Mendes"], d1, CheckinDraft(
        planned=[PlannedItem(summary="Integração de pagamentos com o gateway")],
        blockers=[Blocker(summary="Regra de parcelamento sem definição do produto",
                          category="REQUIREMENT_UNCLEAR", severity="MEDIUM", needs_from="PM")]))
    _history(db, pag, by_name["Bruno Lima"], d1, CheckinDraft(
        planned=[PlannedItem(summary="Concluir a API de cobrança")]))
    db.flush()

    # Impeditivos abertos com a idade do protótipo (o de Diego já existia: id 2).
    for imp in db.scalars(select(Impediment)):
        if imp.member_id == by_name["Ana Souza"].id or imp.summary.startswith("Ambiente"):
            imp.opened_on = d3
        else:
            imp.opened_on = d1


def run() -> None:
    init_db()
    with db_session() as db:
        seed(db)
    print("Seed aplicado (ou já existia).")


if __name__ == "__main__":
    run()
