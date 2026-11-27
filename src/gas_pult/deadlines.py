"""«Подписки и балансы» на экране «Сегодня» (владелец 27.11, GAS-60 Ф1: «отдельная рубрика подписок, балансов, токенов и
сессий, чтобы ничего не пропускать»). Только чтение — пульт ничего не пишет:

- реестры сроков (``config.deadlines`` — пути к markdown-файлам с таблицей, где есть колонка «Когда кончается» в
  формате ДД.ММ.ГГГГ; тот же формат читает ежедневная проверка сроков штаба);
- неделя подписки Claude — какие пороги уже пройдены и когда сброс (``gas-alerts/claude-limits.json``);
- расход по ценам API за сутки — первая строка команды ``config.cost_cmd`` (кэш 10 минут).

«Осталось N дней», пороги 14 / 3 / 1; просроченное — отдельным уровнем (панель рисует красным). Строки без даты не
прячутся — уровень ``none``. Только стандартная библиотека.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

DATE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
COL = "Когда кончается"
LEVELS = ((1, "d1"), (3, "d3"), (14, "d14"))     # дней до срока (сегодня — 0) → уровень; больше — "ok"
COST_TTL = 600
_cost: dict = {"at": 0.0, "cmd": "", "text": ""}


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _plain(s: str) -> str:
    return " ".join(re.sub(r"\*\*|`", "", s).split())


def rows(text: str) -> list[dict]:
    """Строки таблиц с колонкой «Когда кончается»: что, когда, баланс (если есть такая колонка)."""
    out, head = [], None
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            head = None
            continue
        cells = _cells(line)
        if head is None:
            head = cells if COL in cells else None
            continue
        if set("".join(cells)) <= set("-: "):            # строка-разделитель |---|
            continue
        rec = dict(zip(head, cells, strict=False))
        what = _plain(rec.get("Что") or cells[0])
        if what:
            out.append({"what": what, "when": _plain(rec.get(COL, "")), "balance": _plain(rec.get("Баланс", ""))})
    return out


def level(days: int | None) -> str:
    if days is None:
        return "none"
    if days < 0:
        return "over"
    return next((name for n, name in LEVELS if days <= n), "ok")


def items(files: list[str], today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    out = []
    for f in files:
        try:
            text = Path(os.path.expanduser(f)).read_text(encoding="utf-8")
        except OSError:
            continue
        for r in rows(text):
            m = DATE.search(r["when"])
            days = None
            if m:
                try:
                    days = (dt.date(int(m[3]), int(m[2]), int(m[1])) - today).days
                except ValueError:
                    days = None
            out.append({**r, "days": days, "level": level(days)})
    order = {"over": 0, "d1": 1, "d3": 2, "d14": 3, "ok": 4, "none": 5}
    out.sort(key=lambda x: (order[x["level"]], x["days"] if x["days"] is not None else 10 ** 6))
    return out


def claude_week(f: Path | None = None) -> dict | None:
    """Неделя подписки Claude: пройденные пороги (%) и время сброса — из файла оповещений о лимите."""
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    f = f or state / "gas-alerts" / "claude-limits.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    marks = sorted(int(x) for x in d.get("sent") or [] if isinstance(x, (int, float)))
    reset = d.get("reset")
    return {"passed": marks[-1] if marks else 0, "reset": int(reset) if isinstance(reset, (int, float)) else None}


def cost(cmd: str, now: float | None = None) -> str:
    """Первая строка вывода команды расхода (например, «За 24 ч: $86.91»); кэш 10 минут; ошибка — пусто."""
    now = time.time() if now is None else now
    if not cmd:
        return ""
    if _cost["cmd"] == cmd and now - _cost["at"] < COST_TTL:
        return _cost["text"]
    try:
        r = subprocess.run(shlex.split(os.path.expanduser(cmd)), capture_output=True, text=True, timeout=60)
        text = (r.stdout.strip().splitlines() or [""])[0][:200] if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired, ValueError):
        text = ""
    _cost.update(at=now, cmd=cmd, text=text)
    return text


def listing(files: list[str], cost_cmd: str = "") -> dict:
    return {"items": items(files), "claude": claude_week(), "cost": cost(cost_cmd), "configured": bool(files)}
