"""«Поручения» (владелец 27.11, GAS-60 Ф1; решение portfolio-hq 0011): что отправлено, кому и что с этим сейчас.

Пишет одна команда — ``track`` штаба (``~/.local/state/tracks/tracks.json``); пульт только читает: ни одной записи
отсюда, конфликтов нет. Для владельца — состояние, когда обновлено, как проверяется; открытое без движения дольше
суток — ``stale`` (панель рисует красным). Закрытые не прячутся — отдаются тоже. ``owner`` — ждёт владельца
(«владелец» в «кому» или «нужно решение»): блок «Решить сегодня» на экране «Сегодня», ``age_h`` — сколько часов ждёт.
Только стандартная библиотека.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

STALE_H = 24                                     # без движения дольше — красным
OPEN_NOT = ("закрыта",)                          # состояния, после которых поручение не «висит»
STATES = ("передана", "принята", "в_работе", "готово", "ответ_получен", "нужно_решение", "провал", "закрыта")


def path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "tracks" / "tracks.json"


def _ts(s: str) -> float:
    try:
        return time.mktime(time.strptime(str(s or "")[:16], "%Y-%m-%d %H:%M"))
    except (ValueError, OverflowError):
        return 0.0


def check_of(t: dict) -> str:
    """Как проверяется — словами, без номеров чатов."""
    watch = str(t.get("watch") or "")
    if watch.startswith("tg:"):
        return "ответ в Telegram — проверка раз в 5 минут"
    if t.get("pr"):
        return "пулл-реквест " + str(t["pr"])
    if t.get("window"):
        return "окно «" + str(t["window"]) + "» отметит готово"
    return "вручную — командой track"


def listing(f: Path | None = None, now: float | None = None) -> dict:
    """Все поручения, открытые сверху (по времени обновления, свежие первыми). Файла нет — пусто, ``src: False``."""
    f, now = f or path(), time.time() if now is None else now
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"src": False, "tasks": []}
    out = []
    for t in raw.get("tasks") or [] if isinstance(raw, dict) else []:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        state = str(t.get("state") or "передана")
        upd = _ts(t.get("updated") or t.get("created"))
        log = [x for x in t.get("log") or [] if isinstance(x, dict)]
        is_open = state not in OPEN_NOT
        to = str(t.get("to") or "")
        out.append({"id": str(t["id"]), "what": str(t.get("what") or ""), "to": to,
                    "owner": is_open and ("владелец" in to.lower() or state == "нужно_решение"),   # «Решить сегодня»
                    "age_h": round((now - (_ts(t.get("created")) or now)) / 3600, 1),
                    "state": state, "open": is_open, "created": str(t.get("created") or ""),
                    "updated": str(t.get("updated") or ""), "check": check_of(t),
                    "last": str(log[-1].get("note") or "") if log else "",
                    "stale": is_open and bool(upd) and now - upd > STALE_H * 3600})
    out.sort(key=lambda x: (not x["open"], -_ts(x["updated"])))
    return {"src": True, "tasks": out}
