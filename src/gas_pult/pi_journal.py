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

from gas_pult.focus import guest_unmark

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
            t = guest_unmark(text_of(m.get("content")))       # пометка пульта «кто пишет» — не слова человека
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


def overlay_block(text: str) -> str:
    """Блок между ``<!-- overlay -->`` и ``<!-- /overlay -->`` (профили моделей); нет закрывающей — до конца."""
    m = re.search(r"<!-- overlay -->\n?(.*?)(?:<!-- /overlay -->|\Z)", text, re.S)
    return (m.group(1) if m else text).strip()


def compose_overlay(src: Path, model: str) -> str:
    """Свод главных правил (``_core-short.md``) первым, затем оверлей модели (``<model>.md``)."""
    parts = []
    for name in ("_core-short.md", f"{model}.md"):
        f = Path(src) / name
        if f.is_file():
            parts.append(overlay_block(f.read_text(encoding="utf-8")))
    if not parts:
        raise ValueError(f"нет ни _core-short.md, ни {model}.md в {src}")
    return "\n\n".join(parts) + "\n"


TOOLS = {"bash": "Bash", "read": "Read", "edit": "Edit", "write": "Write", "grep": "Grep", "find": "Glob",
         "ls": "Bash"}


def status(f: Path | None) -> dict:
    """Статус последнего хода по журналу Pi — в той же форме, что ``activity.parse`` у Claude Code: ``phase``
    (idle, started, thinking, working, done), ``text``, ``tool``, ``since``, ``turn``, ``last``, ``said``.
    Ход закончен, когда ответ агента пришёл с ``stopReason: "stop"`` без вызова инструмента; ``toolUse`` — ход идёт."""
    from gas_pult import activity  # активность — общий словарь текстов и описание инструментов
    turn = last = said = 0.0
    done, state, open_tools = True, "idle", {}
    for e in _rows(f) if f else ():
        m, ts = e["message"], activity.stamp(e.get("timestamp", ""))
        last = ts or last
        role = m.get("role")
        if role == "user" and text_of(m.get("content")):
            turn, done, state, open_tools = ts, False, "started", {}
        elif role == "toolResult":
            open_tools.pop(str(m.get("toolCallId")), None)
            state = "thinking"
        elif role == "assistant":
            blocks = m.get("content") if isinstance(m.get("content"), list) else []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "toolCall":
                    open_tools[str(b.get("id"))] = (str(b.get("name", "")), b.get("arguments") or {}, ts)
                    state = "tool"
                elif b.get("type") == "thinking":
                    state = "thinking"
                elif b.get("type") == "text" and str(b.get("text", "")).strip():
                    state, said = "text", ts or said
            kinds = {b.get("type") for b in blocks if isinstance(b, dict)}
            if m.get("stopReason") == "stop" and "toolCall" not in kinds and kinds - {"thinking"}:
                done, state, open_tools = True, "done", {}
    out = {"turn": turn, "last": last, "said": said, "prompt": "", "queued": 0, "enq": 0.0, "picked": 0.0, "tool": ""}
    T = activity.TEXTS
    if not turn and not last:
        return {**out, "phase": "idle", "text": "", "since": 0.0}
    if done:
        return {**out, "phase": "done", "text": T["done"], "since": last}
    if open_tools:
        name, arg, ts = list(open_tools.values())[-1]
        a = dict(arg) if isinstance(arg, dict) else {}
        a.setdefault("file_path", a.get("path", ""))
        return {**out, "phase": "working", "text": activity.describe(TOOLS.get(name, name), a), "tool": name,
                "since": ts or last}
    if state == "started":
        return {**out, "phase": "started", "text": T["started"], "since": turn}
    return {**out, "phase": "thinking", "text": T["thinking"], "since": last}


def answers(f: Path) -> list[str]:
    """Законченные ответы агента по порядку: текст хода, завершённого ``stopReason: "stop"`` (для Telegram)."""
    return [t for _, t in answers_at(f)]


def answers_at(f: Path) -> list[tuple[float, str]]:
    """То же с временем записи ответа (Unix): бот отличает ответы до своего запуска от новых."""
    from gas_pult import activity
    out, cur = [], []
    for e in _rows(f):
        m = e["message"]
        if m.get("role") == "user" and text_of(m.get("content")):
            cur = []
        elif m.get("role") == "assistant":
            if t := text_of(m.get("content")):
                cur.append(t)
            kinds = {b.get("type") for b in m.get("content") or [] if isinstance(b, dict)}
            if m.get("stopReason") == "stop" and "toolCall" not in kinds and cur:
                out.append((activity.stamp(e.get("timestamp", "")), "\n\n".join(cur)))
                cur = []
    return out


_windows: dict[str, int] = {}


def window_of(provider: str, model: str, store: Path | None = None) -> int:
    """Окно модели (токены) из каталога Pi ``~/.pi/agent/models-store.json``; нет — 0."""
    key = f"{provider}/{model}"
    if key in _windows:
        return _windows[key]
    try:
        d = json.loads((store or ROOT.parent / "models-store.json").read_text(encoding="utf-8"))
        ms = (d.get(provider) or {}).get("models") or []
        ms = ms.values() if isinstance(ms, dict) else ms
        ms = [m for m in ms if isinstance(m, dict)]
        bare = lambda x: re.sub(r"v\d+(?:\.\d+)?-", "", str(x))          # noqa: E731 — deepseek-v4-flash ≈ deepseek-flash
        w = next((int(m.get("contextWindow") or 0) for m in ms if m.get("id") == model), 0) or \
            next((int(m.get("contextWindow") or 0) for m in ms if bare(m.get("id")) == bare(model)), 0)
    except (OSError, ValueError, TypeError, AttributeError):
        w = 0
    _windows[key] = w
    return w


def usage(f: Path | None, store: Path | None = None) -> dict:
    """Нижняя строка окна Pi — как считает сам Pi (footer.js): ↑ сумма input, ↓ сумма output, R — cacheRead, $ — сумма
    cost.total; контекст — последний запрос к модели (input + cacheRead + cacheWrite + output) / окно модели."""
    from gas_pult import activity
    tot = {"in": 0, "out": 0, "read": 0, "write": 0, "cost": 0.0}
    last, provider, model, at = 0, "", "", 0.0
    for e in _rows(f) if f else ():
        m = e["message"]
        if m.get("role") != "assistant" or not isinstance(m.get("usage"), dict):
            continue
        u = m["usage"]
        for k, src in (("in", "input"), ("out", "output"), ("read", "cacheRead"), ("write", "cacheWrite")):
            tot[k] += int(u.get(src) or 0)
        tot["cost"] += float((u.get("cost") or {}).get("total") or 0)
        last = sum(int(u.get(k) or 0) for k in ("input", "cacheRead", "cacheWrite", "output"))
        provider, model = str(m.get("provider") or provider), str(m.get("model") or model)
        at = activity.stamp(e.get("timestamp", "")) or at
    win = window_of(provider, model, store) if model else 0
    return {**tot, "cost": round(tot["cost"], 4), "ctx": last, "window": win,
            "used": round(last * 100 / win, 1) if win else None, "provider": provider, "model": model, "at": at}
