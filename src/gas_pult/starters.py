"""Первый разговор: бейджики-сценарии и короткое интервью (GAS-37; владелец 19.11: «когда человек создаёт первую
сессию или первый разговор, ему нужно подсказать, что он хочет — бейджики… чтобы сразу кликнуть, и ему тематично
пошли вопросы»).

Сценарии — файлом ``help/starters.toml`` (правит штаб без кода). ``listing`` — набор для человека: нужное не
подключено (почта, календарь) — вместо бейджика «Подключить …»; наблюдателю — ничего; в демо-пространстве — только
сценарии без почты и календаря (у тестировщика их нет). ``prompt`` — что уйдёт агенту: цель, вопросы по одному с
вариантами (Claude Code — инструментом вопросов, пульт покажет кнопки), потом дело; внешнее — только после «Да».
"""

from __future__ import annotations

import tomllib
from importlib import resources

MAX = 8


def load() -> list[dict]:
    text = resources.files("gas_pult").joinpath("help/starters.toml").read_text(encoding="utf-8")
    return list(tomllib.loads(text).get("starter", []))


def listing(have: set[str], role: str | None, space: bool = False) -> list[dict]:
    """Бейджики человека: [{id, title}] — не больше ``MAX``, без повторов. ``have`` — что подключено: mail, calendar."""
    if role in (None, "viewer"):
        return []
    by = {s["id"]: s for s in load()}
    out: list[dict] = []
    for s in load():
        if s.get("connect"):
            continue                                   # «Подключить …» — только вместо недостающего
        need = s.get("needs", "")
        pick = s
        if need and (space or need not in have):
            pick = None if space else by.get(s.get("instead", ""))
        if pick and pick["id"] not in {x["id"] for x in out}:
            out.append({"id": pick["id"], "title": pick["title"]})
    return out[:MAX]


def prompt(sid: str) -> str:
    """Текст агенту: цель, вопросы по одному с вариантами, потом дело; внешнее — после «Да / Нет / Позже»."""
    s = next((x for x in load() if x["id"] == sid), None)
    if not s:
        raise LookupError("такого сценария нет")
    qs = []
    for i, q in enumerate(s.get("questions", []), 1):
        parts = [x.strip() for x in q.split("|")]
        qs.append(f"{i}. {parts[0]}" + (f" (варианты: {', '.join(parts[1:])})" if len(parts) > 1 else ""))
    return (f"«{s['title']}». Помоги {s['goal']}. Сначала расспроси меня — по одному вопросу за раз, с вариантами "
            "ответа кнопками, если они есть:\n" + "\n".join(qs) + "\nПотом сделай дело и коротко покажи итог. Письма, "
            "встречи, сообщения людям — только после моего ответа «Да / Нет / Позже».")
