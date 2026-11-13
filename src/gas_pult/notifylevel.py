"""Уровень уведомлений на сессию (#189 п. 1, #177): «все», «только вопросы и ошибки», «тихо».

Приём взят у bb (уровни all / input-only / muted на поток), написан заново. Уровень окна хранится в state.json
(``notify_levels``: id окна → уровень); своего нет — берётся общий из «Настроек» бота (``notify``):
«все окна» → all, «только активное» → all для активного и muted для остальных, «выкл» → muted.

Что приходит при каком уровне:

| Событие | all | input | muted |
|---|---|---|---|
| ответ Claude (ход закончен) | да | нет | нет |
| вопрос, меню, разрешение | да | да | нет |
| ошибка, сбой, пауза по расходу | да | да | нет |
"""

from __future__ import annotations

LEVELS = ("all", "input", "muted")
TITLES = {"all": "все", "input": "только вопросы и ошибки", "muted": "тихо"}
WANTS = {"answer": {"all"}, "dialog": {"all", "input"}, "error": {"all", "input"}}


def own(st: dict, wid: str) -> str | None:
    lv = (st.get("notify_levels") or {}).get(wid)
    return lv if lv in LEVELS else None


def level(st: dict, wid: str) -> str:
    """Уровень окна: свой, иначе из общего режима бота."""
    if lv := own(st, wid):
        return lv
    g = st.get("notify") or "all"
    if g == "off":
        return "muted"
    if g == "active":
        return "all" if wid == st.get("active") else "muted"
    return "all"


def wants(st: dict, wid: str, kind: str) -> bool:
    """Слать ли событие ``kind`` (answer / dialog / error) по окну ``wid``."""
    return level(st, wid) in WANTS[kind]


def updated(st: dict, wid: str, lv: str) -> dict:
    """Новый словарь ``notify_levels``: свой уровень окна; ``inherit`` — убрать свой (как у общего режима)."""
    if lv not in (*LEVELS, "inherit"):
        raise ValueError("уровень: all, input, muted или inherit")
    d = {k: v for k, v in (st.get("notify_levels") or {}).items() if v in LEVELS}
    if lv == "inherit":
        d.pop(wid, None)
    else:
        d[wid] = lv
    return d


def moved(st: dict, old: str, new: str) -> dict:
    """Окно пересоздано («Перезапустить», смена модели) — свой уровень переезжает вместе с сессией."""
    d = dict(st.get("notify_levels") or {})
    if old in d:
        d[new] = d.pop(old)
    return d
