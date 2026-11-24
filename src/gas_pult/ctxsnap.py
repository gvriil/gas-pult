"""Модель, усилие, заполнение контекста и лимиты подписки — из снимка строки статуса Claude Code.

Строка статуса (``~/.claude/statusline.py``) на каждое обновление пишет JSON, который ей передал Claude Code, в
``~/.cache/claude-ctx/<session_id>.json`` (0600): ``model.display_name``, ``effort.level``,
``context_window.used_percentage``, ``rate_limits.five_hour|seven_day.{used_percentage, resets_at}``, запасное
усилие ``effort_fallback``. Пульт только читает: экран не разбираем — у участников и в демо его нет, а текст строки
меняется от версии к версии. Нет файла (другой человек, старый Claude Code, строка статуса не настроена) — None,
панель покажет то, что знает сама.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from gas_pult.tmux import UUID

LIMITS = ("five_hour", "seven_day")


def base() -> Path:
    """Папка снимков: ``GAS_PULT_CTX_DIR`` (тесты, другой пользователь), иначе ``~/.cache/claude-ctx``."""
    return Path(os.environ.get("GAS_PULT_CTX_DIR") or Path.home() / ".cache" / "claude-ctx")


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def parse(d: dict, at: float) -> dict:
    """Из сырого снимка — только нужное панели, без путей и стоимости."""
    model = d.get("model") or {}
    effort = (d.get("effort") or {}).get("level") if isinstance(d.get("effort"), dict) else d.get("effort")
    cw = d.get("context_window") or {}
    used = _num(cw.get("used_percentage"))
    limits = {}
    for k in LIMITS:
        x = (d.get("rate_limits") or {}).get(k) or {}
        if (p := _num(x.get("used_percentage"))) is not None:
            limits[k] = {"used": round(p), "resets_at": _num(x.get("resets_at"))}
    return {"model": str(model.get("display_name") or model.get("id") or "")[:40],
            "effort": str(effort or d.get("effort_fallback") or "")[:12],
            "effort_guess": not effort and bool(d.get("effort_fallback")),   # уровень из настроек, а не от Claude
            "used": None if used is None else max(0, min(100, round(used))),
            "size": _num(cw.get("context_window_size")),
            "limits": limits, "at": at}


def read(sid: str, root: Path | None = None) -> dict | None:
    """Снимок сессии ``sid``; нет или не читается — None."""
    if not sid or not UUID.match(sid):
        return None
    f = (root or base()) / f"{sid}.json"
    try:
        at = f.stat().st_mtime
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return parse(d, at) if isinstance(d, dict) else None


def limits(root: Path | None = None, now: float | None = None) -> dict | None:
    """Лимиты подписки — общие на учётку: из самого свежего снимка, где они есть. Время сброса прошло — лимит
    уже обнулился, его не показываем."""
    now = time.time() if now is None else now
    try:
        files = sorted((root or base()).glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:20]
    except OSError:
        return None
    for f in files:
        snap = read(f.stem, root)
        if snap and snap["limits"]:
            out = {k: v for k, v in snap["limits"].items() if not v["resets_at"] or v["resets_at"] > now}
            if not out:
                return None
            w = week(out.get("seven_day"), now)
            return {"limits": out, "at": snap["at"], **({"week": w} if w else {})}
    return None


WEEK = 7 * 86400
WARN, BAD = 70, 85                        # % недели: до 70 — обычный цвет, 70–85 — жёлтый, выше — красный (24.11)


def week(x: dict | None, now: float | None = None) -> dict | None:
    """Недельный лимит подписки и темп (владелец 24.11: «показывать недельные лимиты — а то мы невидимы»):
    used, resets_at, level (ok | warn | bad), proj — сколько будет к сбросу при нынешнем темпе, % (None — рано
    судить), out_at — когда кончится при этом темпе (только если раньше сброса)."""
    if not x or x.get("used") is None or not x.get("resets_at"):
        return None
    now = time.time() if now is None else now
    used, reset = float(x["used"]), float(x["resets_at"])
    gone = now - (reset - WEEK)                          # прошло с начала недели лимита
    proj = out_at = None
    if gone > 3600 and used > 0:                         # первый час — темп ещё ни о чём не говорит
        rate = used / gone                                # % в секунду
        proj = round(used + rate * max(0.0, reset - now))
        t100 = now + (100 - used) / rate if used < 100 else now
        out_at = int(t100) if t100 < reset else None
    level = "bad" if used > BAD else "warn" if used >= WARN else "ok"
    return {"used": round(used), "resets_at": int(reset), "level": level, "proj": proj, "out_at": out_at}


DAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def day(t: float) -> str:
    """«пт 20:00» — день недели и время сервера."""
    from datetime import datetime
    d = datetime.fromtimestamp(t)
    return f"{DAYS[d.weekday()]} {d:%H:%M}"


def week_text(w: dict | None) -> str:
    """Одна строка для бота: «Неделя 71 % · сброс пт 20:00 · к сбросу ≈ 98 %» (время сервера)."""
    if not w:
        return ""
    tail = f" · кончится ≈ {day(w['out_at'])}" if w.get("out_at") else \
        f" · к сбросу ≈ {w['proj']} %" if w.get("proj") is not None else ""
    return f"Неделя {w['used']} % · сброс {day(w['resets_at'])}{tail}"

