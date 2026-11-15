"""Журнал сессий Pi (основной запасной агент, решение владельца 15.11) — для адаптера ``harness.Pi``.

Формат — документация Pi ``docs/session-format.md`` (версия 3): ``~/.pi/agent/sessions/--<путь>--/<время>_<id>.jsonl``;
путь — без начального «/», а «/», «\\» и «:» заменены на «-». Первая строка — заголовок ``{"type": "session", "id",
"cwd"}``; дальше записи ``{"type": "message", "timestamp", "message": {"role", "content"}}``. Роли: ``user`` (текст
или блоки), ``assistant`` (блоки ``text`` / ``thinking`` / ``toolCall``, поле ``model``), ``toolResult``,
``bashExecution``, ``custom``, ``compactionSummary`` и др. — показываем только текст человека и текст ответа.
Ответ агента — весь текст хода до следующего сообщения человека, как у Claude Code. Неизвестные записи и роли —
пропускаем (Pi разрешает свои роли расширениям).
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

ROOT = Path(os.environ.get("PI_CODING_AGENT_SESSION_DIR") or Path.home() / ".pi" / "agent" / "sessions")
SID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def valid_sid(sid) -> str:
    sid = str(sid or "").strip()
    return sid if SID.match(sid) and not sid.endswith((".", "_", "-")) else ""


def project_dir(path: str, root: Path | None = None) -> Path:
    name = re.sub(r"[/\\:]", "-", path.lstrip("/\\"))
    return (root or ROOT) / f"--{name}--"


def current(path: str, root: Path | None = None, sid: str = "") -> Path | None:
    """Журнал сессии ``sid`` в папке проекта (или в любой: окно могло сменить папку); без ``sid`` — последний."""
    d = project_dir(path, root)
    if sid := valid_sid(sid):
        f = next(iter(sorted(d.glob(f"*_{sid}.jsonl"))), None)
        return f or next(iter(sorted((root or ROOT).glob(f"*/*_{sid}.jsonl"))), None)
    files = sorted(d.glob("*.jsonl"))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def text_of(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n\n".join(b.get("text", "").strip() for b in content
                           if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip())
    return ""


def _rows(f: Path):
    with open(f, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("type") == "message" and isinstance(e.get("message"), dict):
                yield e


_cache: dict[str, tuple[tuple, list[dict], str]] = {}
_lock = threading.Lock()


def parse(f: Path) -> tuple[list[dict], str]:
    """(лента [{role, text, ts}], последняя модель). Кэш по (размер, время) файла."""
    st = f.stat()
    key = (st.st_ino, st.st_size, st.st_mtime_ns)
    with _lock:
        c = _cache.get(str(f))
        if c and c[0] == key:
            return c[1], c[2]
    items: list[dict] = []
    model = ""
    for e in _rows(f):
        m, ts = e["message"], str(e.get("timestamp", ""))[:16].replace("T", " ")
        role = m.get("role")
        if role == "user":
            t = text_of(m.get("content"))
            if t:
                items.append({"role": "user", "text": t, "ts": ts})
        elif role == "assistant":
            model = str(m.get("model") or model)
            t = text_of(m.get("content"))
            if not t:
                continue
            if items and items[-1]["role"] == "assistant":
                items[-1]["text"] += "\n\n" + t
            else:
                items.append({"role": "assistant", "text": t, "ts": ts})
    with _lock:
        _cache[str(f)] = (key, items, model)
        if len(_cache) > 32:
            _cache.pop(next(iter(_cache)))
    return items, model


def history(f: Path | None, limit: int = 30, before: int | None = None) -> tuple[list[dict], bool]:
    if not f:
        return [], False
    items, _ = parse(f)
    end = len(items) if before is None else max(0, min(before, len(items)))
    start = max(0, end - limit)
    return [{**it, "i": n} for n, it in enumerate(items[start:end], start)], start > 0


def session_arg(argv: list[str]) -> str:
    """id сессии из аргументов процесса Pi (``--session-id <id>`` или ``--session-id=<id>``); нет — ""."""
    for i, a in enumerate(argv):
        if a == "--session-id" and i + 1 < len(argv):
            return valid_sid(argv[i + 1])
        if a.startswith("--session-id="):
            return valid_sid(a.split("=", 1)[1])
    return ""
