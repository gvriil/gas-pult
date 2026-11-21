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


def _file() -> dict:
    return tomllib.loads(resources.files("gas_pult").joinpath("help/starters.toml").read_text(encoding="utf-8"))


def load() -> list[dict]:
    return list(_file().get("starter", []))


def occupations() -> list[dict]:
    """«Чем вы занимаетесь?» (владелец 19.11): ответы кнопками — [{id, title}]."""
    return [{"id": o["id"], "title": o["title"]} for o in _file().get("occupation", [])]


OCC_MAX = 4


def for_occupation(occ: str, have: set[str], role: str | None, space: bool = False) -> list[dict]:
    """3–4 сценария под занятие: нужное не подключено — «Подключить …» вместо (в пространстве — пропуск)."""
    if role in (None, "viewer"):
        return []
    o = next((x for x in _file().get("occupation", []) if x["id"] == occ), None)
    if not o:
        return []
    by, out = {s["id"]: s for s in load()}, []
    for sid in o.get("starters", []):
        s = by.get(sid)
        if not s:
            continue
        need = s.get("needs", "")
        if need and need not in have:
            s = None if space else by.get(s.get("instead", ""))
        if s and s["id"] not in {x["id"] for x in out}:
            out.append({"id": s["id"], "title": s["title"]})
    return out[:OCC_MAX]


def listing(have: set[str], role: str | None, space: bool = False) -> list[dict]:
    """Бейджики человека: [{id, title}] — не больше ``MAX``, без повторов. ``have`` — что подключено: mail, calendar."""
    if role in (None, "viewer"):
        return []
    by = {s["id"]: s for s in load()}
    out: list[dict] = []
    for s in load():
        if s.get("connect") or s.get("occ_only"):
            continue                                   # «Подключить …» — только вместо недостающего; под занятие — там
        need = s.get("needs", "")
        pick = s
        if need and need not in have:                 # в пространстве — только то, что подключено ему самому
            pick = None if space else by.get(s.get("instead", ""))
        if pick and pick["id"] not in {x["id"] for x in out}:
            out.append({"id": pick["id"], "title": pick["title"]})
    return out[:MAX]


def prompt(sid: str, tasks: bool = False) -> str:
    """Текст агенту: цель, вопросы по одному с вариантами, потом дело; внешнее — после «Да / Нет / Позже».
    ``tasks`` — чат владельца (не пространство): агенту — как ставить задачу по «добавь задачу …» (``TASK_HINT``)."""
    s = next((x for x in load() if x["id"] == sid), None)
    if not s:
        raise LookupError("такого сценария нет")
    qs = []
    for i, q in enumerate(s.get("questions", []), 1):
        parts = [x.strip() for x in q.split("|")]
        qs.append(f"{i}. {parts[0]}" + (f" (варианты: {', '.join(parts[1:])})" if len(parts) > 1 else ""))
    title = s.get("chat_title") or TITLE
    out = (f"«{s['title']}». Помоги {s['goal']}. Сначала расспроси меня — по одному вопросу за раз, с вариантами "
           "ответа кнопками, если они есть:\n" + "\n".join(qs) + "\nКогда поймёшь, о чём чат, назови его по смыслу "
           f"командой gas-pult title \"{title}\" — без кодов и номеров задач.\nПотом сделай дело и коротко покажи "
           "итог.")
    if then := s.get("then"):
        out += f" {then}."
    if name := s.get("template"):
        out += ("\nНад документом по шаблону — строка «Не юридическая консультация». Отправить его — только после "
                "моего «Да».\n\nШаблон:\n" + template(name))
    if tasks:
        out += "\n" + TASK_HINT
    return out + "\nПисьма, встречи, сообщения людям — только после моего ответа «Да / Нет / Позже»."


TITLE = "<кто или что> — <суть>, <сумма или срок>"     # название чата по смыслу (владелец 20.11)
# «Добавь задачу …» из чата (владелец 21.11): задача — в списке владельца со ссылкой на этот чат
TASK_HINT = ("Если попрошу «добавь задачу …» — поставь её командой gas-pult task add \"<что сделать>\" "
             "(срок — --due ГГГГ-ММ-ДД, срочно — --urgent yes; чат подставится сам) и коротко подтверди.")


def template(name: str) -> str:
    """Шаблон документа из ``help/templates/<имя>.md`` (имя — только буквы, цифры и дефис)."""
    if not name.replace("-", "").isalnum():
        raise LookupError("такого шаблона нет")
    try:
        return resources.files("gas_pult").joinpath(f"help/templates/{name}.md").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise LookupError("такого шаблона нет") from None
