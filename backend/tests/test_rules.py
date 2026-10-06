from datetime import date

from app.domain import rules


def test_business_days_skip_weekend():
    friday, monday = date(2026, 10, 2), date(2026, 10, 5)
    assert rules.business_days_between(friday, monday) == 1
    assert rules.business_days_between(monday, monday) == 0
    assert rules.business_days_between(date(2026, 9, 30), monday) == 3


def test_previous_business_day_from_monday_is_friday():
    assert rules.previous_business_day(date(2026, 10, 5)) == date(2026, 10, 2)


def test_aged_is_strictly_above_threshold():
    assert rules.is_aged(3, 2) and not rules.is_aged(2, 2)


def test_repeated_items_needs_streak():
    today = ["Integração de pagamentos com o gateway"]
    prev = [["Integração de pagamentos com gateway"], ["integração de pagamentos com o gateway"], ["outra coisa"]]
    assert rules.repeated_items(today, prev, min_days=3) == [(today[0], 3)]
    assert rules.repeated_items(today, prev[:1], min_days=3) == []


def test_unfulfilled_plan():
    missed = rules.unfulfilled_plan(["Concluir a API de cobrança", "Revisar PRs"], ["Revisar PRs pendentes"], [])
    assert missed == ["Concluir a API de cobrança"]
