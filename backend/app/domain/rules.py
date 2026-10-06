"""Regras simples que rodam em código (não no LLM).

O código calcula os fatos (idade, repetição, plano não cumprido). O LLM só interpreta
e prioriza. Assim os números do report nunca são alucinados.
"""
from datetime import date, timedelta
from difflib import SequenceMatcher

SIMILARITY = 0.6  # acima disso, dois textos são tratados como "o mesmo item"


def business_days_between(start: date, end: date) -> int:
    """Dias úteis (seg-sex) em (start, end]. Aberto numa sexta, na segunda = 1."""
    days, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days += 1
    return days


def previous_business_day(day: date) -> date:
    d = day - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def age_label(days: int) -> str:
    if days == 0:
        return "aberto hoje"
    return "1 dia útil" if days == 1 else f"{days} dias úteis"


def is_aged(days: int, threshold: int) -> bool:
    return days > threshold


def similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio() >= SIMILARITY


def repeated_items(today: list[str], previous_days: list[list[str]], min_days: int = 3) -> list[tuple[str, int]]:
    """Itens planejados hoje que também estavam no plano de cada um dos dias anteriores.

    `previous_days` vem do mais recente para o mais antigo. Devolve (item, nº de dias seguidos),
    só para quem chegou a `min_days`.
    """
    result = []
    for item in today:
        streak = 1
        for day_items in previous_days:
            if any(similar(item, other) for other in day_items):
                streak += 1
            else:
                break
        if streak >= min_days:
            result.append((item, streak))
    return result


def unfulfilled_plan(previous_plan: list[str], done_today: list[str], planned_today: list[str]) -> list[str]:
    """Itens do plano de ontem que hoje não aparecem nem como feitos nem como planejados."""
    mentioned = done_today + planned_today
    return [p for p in previous_plan if not any(similar(p, m) for m in mentioned)]
