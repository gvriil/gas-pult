"""Расход по ценам API (владелец 22.11): строки «💰 По ценам API за HH:MM–HH:MM: $X» больше не идут в каждый чат —
панель показывает их одним экраном «Расход». Считает их внешний скрипт раз в час и кладёт в очередь оповещений
(JSON Lines: ``{"ts": unix, "text": "..."}``); здесь — только чтение этой очереди и свод за период. Скрипт панель не
запускает (он тяжёлый).

Запись::

    💰 По ценам API за 23:00–00:00: $15.15
      shtab: $6.78
      gas-pult: $3.70
      с начала суток: $0.00

Час — из «за HH:MM–HH:MM» относительно даты ``ts`` (местное время сервера): запись приходит в начале следующего
часа, поэтому час 23:00–00:00 с ``ts`` в 00:01 — это прошлые сутки. Строка «с начала суток» — не проект.
Путь к очереди — ``GAS_PULT_SPEND_FILE`` (по умолчанию ``~/.local/state/gas-alerts/queue.jsonl``).
"""

import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

ENV = "GAS_PULT_SPEND_FILE"
DEFAULT = "~/.local/state/gas-alerts/queue.jsonl"
PERIODS = ("today", "yesterday", "7d")
OTHER = "прочее"                                    # итог часа больше суммы перечисленных проектов

HEAD = re.compile(r"^💰 По ценам API за (\d{1,2}):(\d{2})\s*[–—-]\s*(\d{1,2}):(\d{2}):\s*\$\s*([\d.,]+)")
LINE = re.compile(r"^\s+(.+?):\s*\$\s*([\d.,]+)\s*$")
_cache: dict = {}


def path() -> Path:
    return Path(os.environ.get(ENV) or DEFAULT).expanduser()


def _usd(s: str) -> float:
    return float(s.replace(",", "."))


def parse(ts, text) -> dict | None:
    """Одна запись очереди → ``{"day", "hour", "total", "projects", "ts"}``; чужая или битая — ``None``."""
    if not isinstance(text, str) or not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return None
    lines = text.splitlines()
    m = HEAD.match(lines[0]) if lines else None
    if not m:
        return None
    try:
        hour, total, at = int(m.group(1)), _usd(m.group(5)), datetime.fromtimestamp(ts)
    except (ValueError, OverflowError, OSError):
        return None
    if not 0 <= hour <= 23:
        return None
    start = at.replace(hour=hour, minute=0, second=0, microsecond=0)
    if start > at:                                   # 23:00–00:00 пришло в 00:01 — это прошлые сутки
        start -= timedelta(days=1)
    projects: dict[str, float] = {}
    for ln in lines[1:]:
        p = LINE.match(ln)
        if not p or p.group(1).strip().lower().startswith("с начала суток"):
            continue
        try:
            projects[p.group(1).strip()] = projects.get(p.group(1).strip(), 0.0) + _usd(p.group(2))
        except ValueError:
            continue
    return {"day": start.date(), "hour": start.hour, "total": total, "projects": projects, "ts": float(ts)}


def records(src: Path | None = None) -> list[dict]:
    """Все записи расхода из очереди; повтор того же часа — последняя запись. Кэш — по mtime и размеру файла."""
    src = src or path()
    try:
        st = src.stat()
    except OSError:
        return []
    key = (str(src), st.st_mtime_ns, st.st_size)
    if _cache.get("key") == key:
        return _cache["rows"]
    by: dict = {}
    with open(src, encoding="utf-8", errors="replace") as f:
        for ln in f:
            if "По ценам API" not in ln:
                continue
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            r = parse(d.get("ts"), d.get("text")) if isinstance(d, dict) else None
            if r:
                by[(r["day"], r["hour"])] = r
    rows = sorted(by.values(), key=lambda r: (r["day"], r["hour"]))
    _cache.update(key=key, rows=rows)
    return rows


def summary(period: str = "today", now: datetime | None = None, src: Path | None = None) -> dict:
    """Свод за «сегодня», «вчера» или 7 дней: итог, проекты по убыванию, столбики по часам (или по дням)."""
    if period not in PERIODS:
        raise ValueError("период — today, yesterday или 7d")
    today = (now or datetime.now()).date()
    days: list[date] = ([today] if period == "today" else [today - timedelta(days=1)] if period == "yesterday"
                        else [today - timedelta(days=i) for i in range(6, -1, -1)])
    rows = records(src)
    mine = [r for r in rows if r["day"] in days]
    projects: dict[str, float] = {}
    for r in mine:
        for k, v in r["projects"].items():
            projects[k] = projects.get(k, 0.0) + v
        rest = r["total"] - sum(r["projects"].values())
        if rest >= 0.005:
            projects[OTHER] = projects.get(OTHER, 0.0) + rest
    out = {"period": period, "total": round(sum(r["total"] for r in mine), 2),
           "projects": [{"name": k, "usd": round(v, 2)} for k, v in sorted(projects.items(), key=lambda kv: -kv[1])
                        if round(v, 2) > 0],
           "updated": rows[-1]["ts"] if rows else None, "from": days[0].isoformat(), "to": days[-1].isoformat()}
    if period == "7d":
        out["days"] = [{"date": d.isoformat(), "usd": round(sum(r["total"] for r in mine if r["day"] == d), 2)}
                       for d in days]
    else:
        out["hours"] = [{"h": h, "usd": round(sum(r["total"] for r in mine if r["hour"] == h), 2)} for h in range(24)]
    return out
