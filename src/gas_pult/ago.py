"""Когда сессия менялась в последний раз: «12 с назад» → «5 мин» → «3 ч» → «вчера» → «4 дн» → «2 нед» → «3 мес» →
дата. Точное время — «03.11, 06:41:12» (местный часовой пояс).

Шкала (секунды от изменения до «сейчас»; будущее из-за расхождения часов — как «только что»):
до 5 с — «только что»; до минуты — секунды; до часа — минуты; до суток — часы; до двух суток — «вчера»;
до недели — дни; до 30 дней — недели (дни // 7); до 365 дней — месяцы (дни // 30); дальше — дата.

Тексты — в словарях панели ``web/i18n/ru.json`` и ``en.json`` (ключи ``ago.*``), те же правила — в ``index.html``
(``agoText``): тест прогоняет обе реализации по одной таблице. Короткая форма — для карточек («5 мин»), полная —
для шапки и бота («5 минут назад», «1 минуту назад», «2 минуты назад»).

Последнее изменение сессии — последний ход в журнале jsonl или смена экрана окна (``Screens``): что новее.
Только стандартная библиотека.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time

from gas_pult import humanize

MIN, HOUR, DAY = 60, 3600, 86400
STALE = 7 * DAY                 # давно без изменений — приглушить и подсказать «можно завершить»
# (до скольких секунд, единица): единица → ключ словаря ago.<u> (короткая) и ago.<u>.one|few|many (полная)
STEPS = ((5, "now"), (MIN, "s"), (HOUR, "min"), (DAY, "h"), (2 * DAY, "yesterday"), (7 * DAY, "d"),
         (30 * DAY, "w"), (365 * DAY, "mo"))
UNIT = {"s": 1, "min": MIN, "h": HOUR, "d": DAY, "w": 7 * DAY, "mo": 30 * DAY}


def plural(n: int, lang: str = "ru") -> str:
    """Форма числа: ru — one (1, 21), few (2–4, 22), many (5–20, 11–14); en — one (1) и many (остальные)."""
    n = abs(int(n))
    if lang != "ru":
        return "one" if n == 1 else "many"
    if n % 10 == 1 and n % 100 != 11:
        return "one"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "few"
    return "many"


def tr(lang: str, key: str, **kw) -> str:
    s = humanize.dictionary(lang if lang in ("ru", "en") else "ru").get(key, key)
    for k, v in kw.items():
        s = s.replace("{" + k + "}", str(v))
    return s


def _parts(ts: float) -> dict:
    t = time.localtime(ts)
    return {"d": f"{t.tm_mday:02d}", "m": f"{t.tm_mon:02d}", "y": str(t.tm_year),
            "t": f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"}


def ago(ts: float | None, now: float | None = None, lang: str = "ru", full: bool = False) -> str:
    """Сколько прошло: короткая форма («5 мин») или полная (``full``: «5 минут назад»); нет времени — ""."""
    if not ts:
        return ""
    now = time.time() if now is None else now
    sec = max(0, int(now - ts))
    for limit, unit in STEPS:
        if sec < limit:
            if unit in ("now", "yesterday"):
                return tr(lang, "ago." + unit)
            n = sec // UNIT[unit]
            return tr(lang, f"ago.{unit}.{plural(n, lang)}" if full else f"ago.{unit}", n=n)
    return tr(lang, "ago.date", **_parts(ts))


def exact(ts: float | None, now: float | None = None, lang: str = "ru") -> str:
    """Точное время по местному поясу: «03.11, 06:41:12»; другой год — «03.11.2025, 06:41:12»."""
    if not ts:
        return ""
    now = time.time() if now is None else now
    p = _parts(ts)
    same = time.localtime(now).tm_year == time.localtime(ts).tm_year
    return tr(lang, "ago.exact" if same else "ago.exact.year", **p)


def stale(ts: float | None, now: float | None = None) -> bool:
    """Давно без изменений (больше 7 дней)."""
    return bool(ts) and (time.time() if now is None else now) - ts > STALE


def stamps(journal: dict | None, screen_at: float = 0.0, mtime: float = 0.0) -> dict:
    """Времена сессии для API: ``changed`` — последнее изменение (ход в журнале или экран), ``said`` — последний
    ответ агента, ``asked`` — последнее сообщение человека. Неизвестно — None. ``mtime`` журнала — запасной вариант,
    если в хвосте журнала нет ни одной записи со временем."""
    j = journal or {}
    said, asked = j.get("said") or 0.0, j.get("turn") or 0.0
    changed = max(j.get("last") or 0.0, said, asked, screen_at or 0.0) or mtime or 0.0
    return {"changed": changed or None, "said": said or None, "asked": asked or None}


def line(st: dict, now: float | None = None, lang: str = "ru") -> str:
    """Строка для бота: «изменена 5 минут назад (03.11, 06:41:12) · ответ агента — 7 минут назад · ваше сообщение
    — 10 минут назад»; ответ и сообщение — только если отличаются от последнего изменения."""
    ch = st.get("changed")
    if not ch:
        return ""
    out = [tr(lang, "ago.changed", ago=ago(ch, now, lang, True)) + f" ({exact(ch, now, lang)})"]
    for key in ("said", "asked"):
        ts = st.get(key)
        if ts and abs(ch - ts) >= 1 and ago(ts, now, lang, True) != ago(ch, now, lang, True):
            out.append(tr(lang, "ago." + key, ago=ago(ts, now, lang, True)))
    return " · ".join(out)


# ---------- смена экрана окна ----------
RULE = re.compile(r"^\s*[─━]{8,}\s*$")


def screen_key(lines: list[str]) -> str:
    """Отпечаток экрана без поля ввода и строки статуса под ним (там бывают часы и счётчики): всё выше верхней
    рамки поля ввода — она предпоследняя линия «────» на экране Claude Code."""
    rules = [i for i, s in enumerate(lines) if RULE.match(s)]
    body = lines[:rules[-2]] if len(rules) >= 2 else lines
    return hashlib.sha1("\n".join(s.rstrip() for s in body).encode()).hexdigest()[:16]


class Screens:
    """Когда экран окна менялся (только в памяти процесса). Первый взгляд — время неизвестно (0): после перезапуска
    пульта не считаем все окна «только что изменёнными»."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.seen: dict[str, tuple[str, float]] = {}
        self.lock = threading.Lock()

    def look(self, wid: str, lines: list[str]) -> float:
        key = screen_key(lines)
        with self.lock:
            old = self.seen.get(wid)
            at = (old[1] if old[0] == key else self.clock()) if old else 0.0
            self.seen[wid] = (key, at)
            return at

    def at(self, wid: str) -> float:
        with self.lock:
            return (self.seen.get(wid) or ("", 0.0))[1]
