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
            return {"limits": out, "at": snap["at"]} if out else None
    return None
