"""Интеграции на чат (владелец 19.11: «как у Claude: текстовое окно, можно выбрать много настроек, интеграции»).

Человек выключает интеграцию в новом чате или посреди чата — Claude Code этого чата запускается с
``--disallowedTools mcp__<сервер>``: инструменты выключенного сервера модели не видны, остальные — как были.
Проверено 19.11 на Claude Code 2.1.328: с запретом ``mcp__claude_ai_Gmail`` инструментов Gmail 0, Calendar 9; без
запрета — 31 и 9. ``--strict-mcp-config`` не годится: убирает и коннекторы claude.ai.

Набор выключенных — у разговора (id сессии Claude Code), файл ``<данные>/chat-mcp.json`` (0600): перезапуск,
«Продолжить» и смена поставщика его сохраняют. Только Claude Code; у Pi, OpenCode, Hermes — свой способ, здесь нет.
"""

from __future__ import annotations

import json
import re
import shlex
import threading
from pathlib import Path

from gas_pult.config import write_private

_lock = threading.Lock()
MAX = 64


def prefix(name: str) -> str:
    """Имя сервера из ``claude mcp list`` → начало имён его инструментов: «claude.ai Gmail» → mcp__claude_ai_Gmail."""
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", str(name or "").strip())


def norm(off) -> list[str]:
    if not isinstance(off, (list, tuple)):
        return []
    out = []
    for x in off:
        x = " ".join(str(x or "").split())[:120]
        if x and x not in out:
            out.append(x)
    return out[:MAX]


def _load(path: Path) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def get(path: Path, sid: str) -> list[str]:
    return norm(_load(path).get(str(sid or ""))) if sid else []


def put(path: Path, sid: str, off) -> list[str]:
    if not sid:
        return []
    off = norm(off)
    with _lock:
        d = _load(path)
        if off:
            d[str(sid)] = off
        else:
            d.pop(str(sid), None)
        write_private(Path(path), json.dumps(d, ensure_ascii=False))
    return off


def flags(off) -> str:
    """Добавка к команде claude. Значения ``--disallowedTools`` — одним аргументом; дальше идут только флаги."""
    off = norm(off)
    return f" --disallowedTools {shlex.quote(' '.join(prefix(x) for x in off))}" if off else ""
