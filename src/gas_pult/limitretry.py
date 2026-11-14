"""Один отложенный повтор после лимита подписки (#189 п. 6, приём bb «provider retry»; код свой).

Сессия упёрлась в лимит подписки (5 часов или неделя), запасных поставщиков нет — она стоит, пока человек не напишет
«продолжай» после сброса лимита. Теперь пульт ставит ОДИН повтор на время сброса: ``limit_retries`` в state.json,
запись на окно — новая заменяет старую, поэтому повторы не копятся (у bb было 28 «Please continue.» в очереди).
В назначенное время — «продолжай» в это окно, если с момента остановки человек сам не писал туда (новое сообщение
обгоняет повтор — повтор снимается) и окно свободно. Сброс дальше ``MAX_WAIT`` — повтор не ставим, говорим.

Время сброса: снимок строки статуса (``ctxsnap.limits``: лимит, использованный на 100 %, и его ``resets_at``),
иначе текст ошибки Claude Code: «…|1731600000» или «resets 3pm» / «resets 15:30».
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

MAX_WAIT = 6 * 3600          # дальше — не ставим (как у bb по умолчанию)
SLACK = 60                   # с после сброса: лимит у поставщика обновляется не мгновенно
TEXT = "Лимит подписки обновился — продолжай с того места, где остановился."
EPOCH = re.compile(r"\|\s*(\d{10})\b")
AT = re.compile(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.I)


def reset_from_snapshot(limits: dict | None, now: float) -> float | None:
    """Лимит, использованный на 100 %, — его время сброса (позднейшее, если оба)."""
    x = (limits or {}).get("limits") or {}
    ts = [v["resets_at"] for v in x.values() if v.get("used", 0) >= 100 and (v.get("resets_at") or 0) > now]
    return max(ts) if ts else None


def reset_from_text(text: str, now: float) -> float | None:
    """Время сброса из текста ошибки: метка «|1731600000» или «resets 3pm» (местное время сервера)."""
    if m := EPOCH.search(text or ""):
        t = float(m.group(1))
        return t if t > now else None
    if m := AT.search(text or ""):
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        if h > 23 or mi > 59:
            return None
        base = datetime.fromtimestamp(now)
        at = base.replace(hour=h, minute=mi, second=0, microsecond=0)
        if at.timestamp() <= now:
            at += timedelta(days=1)
        return at.timestamp()
    return None


def reset_at(text: str, limits: dict | None, now: float | None = None) -> float | None:
    now = time.time() if now is None else now
    return reset_from_snapshot(limits, now) or reset_from_text(text, now)


def schedule(st: dict, wid: str, name: str, at: float, now: float | None = None) -> dict:
    """Новый ``limit_retries``: одна запись на окно (новая заменяет старую)."""
    now = time.time() if now is None else now
    d = {k: v for k, v in (st.get("limit_retries") or {}).items() if isinstance(v, dict)}
    d[wid] = {"at": at + SLACK, "since": now, "name": name}
    return d


def cancel(st: dict, wid: str) -> dict:
    d = dict(st.get("limit_retries") or {})
    d.pop(wid, None)
    return d


def due(st: dict, now: float | None = None) -> list[tuple[str, dict]]:
    now = time.time() if now is None else now
    return [(w, r) for w, r in (st.get("limit_retries") or {}).items() if isinstance(r, dict) and r.get("at", 0) <= now]


def hhmm(ts: float, now: float | None = None) -> str:
    now = time.time() if now is None else now
    d = datetime.fromtimestamp(ts)
    same = d.date() == datetime.fromtimestamp(now).date()
    return d.strftime("%H:%M") if same else d.strftime("%d.%m %H:%M")
