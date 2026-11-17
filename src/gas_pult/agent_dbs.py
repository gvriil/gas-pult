"""Журналы OpenCode и Hermes для пульта (владелец 17.11: «Hermes и OpenCode нельзя открыть окном в пульте»).

Обе программы хранят разговоры в SQLite — пульт читает их только на чтение (``mode=ro``), сами программы не
запускает:

- OpenCode — ``~/.local/share/opencode/opencode.db``: ``session`` (``id``, ``directory``, ``title``), ``message``
  (``data``: ``role``, ``time.created``, у ответа — ``modelID``, ``providerID``, ``tokens``, ``finish``), ``part``
  (``data``: ``type`` = ``text`` | ``reasoning`` | ``tool`` …, ``text``).
- Hermes — ``~/.hermes/state.db``: ``sessions`` (``id``, ``cwd``, ``model``, ``title``, ``last_activity_at``,
  ``transcript_revision``), ``messages`` (``role``, ``content``, ``timestamp``, ``finish_reason``).

Лента — тот же вид, что у Pi и Claude Code: ``[{role, text, ts}]``. Id сессии заранее задать нельзя (обе программы
создают его сами), поэтому журнал окна — сессия с этим id, а без id — самая свежая сессия папки окна (правило пульта:
одно окно на проект). Только стандартная библиотека.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

_SID = re.compile(r"^[A-Za-z0-9_.:-]{6,120}$")


def valid_sid(s) -> str:
    s = str(s or "").strip()
    return s if _SID.match(s) else ""


@dataclass(frozen=True)
class Ref:
    """Журнал окна в базе: какая база, какая сессия. ``str(ref)`` — ключ для «уже видел ответы» в боте."""
    db: Path
    sid: str

    def __str__(self) -> str:
        return f"{self.db}#{self.sid}"


def _open(db: Path):
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)


def _ts(sec) -> str:
    """Секунды (или миллисекунды) эпохи → «ГГГГ-ММ-ДД ЧЧ:ММ» UTC, как в журналах Claude Code."""
    try:
        v = float(sec)
    except (TypeError, ValueError):
        return ""
    if v > 1e11:                                     # OpenCode хранит миллисекунды
        v /= 1000
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(v))


# ---------- OpenCode ----------
class OpenCodeDB:
    def __init__(self, db: Path | None = None):
        self.db = Path(db) if db else Path.home() / ".local/share/opencode/opencode.db"

    def latest(self, path: str) -> str:
        if not self.db.is_file():
            return ""
        try:
            with _open(self.db) as c:
                r = c.execute("select id from session where directory = ? and parent_id is null "
                              "order by time_updated desc limit 1", (str(path),)).fetchone()
        except sqlite3.Error:
            return ""
        return r[0] if r else ""

    def ref(self, path: str, sid: str = "") -> Ref | None:
        sid = valid_sid(sid) or self.latest(path)
        return Ref(self.db, sid) if sid else None

    def rows(self, ref: Ref) -> list[dict]:
        """Сообщения сессии по порядку: [{role, text, ts, model, finish, tokens}] — текст из частей ``text``."""
        try:
            with _open(ref.db) as c:
                msgs = c.execute("select id, data from message where session_id = ? order by time_created",
                                 (ref.sid,)).fetchall()
                parts: dict[str, list[str]] = {}
                for mid, d in c.execute("select message_id, data from part where session_id = ? "
                                        "order by time_created", (ref.sid,)):
                    p = json.loads(d)
                    if p.get("type") == "text" and p.get("text") and not p.get("synthetic"):
                        parts.setdefault(mid, []).append(p["text"])
        except (sqlite3.Error, ValueError):
            return []
        out = []
        for mid, d in msgs:
            try:
                m = json.loads(d)
            except ValueError:
                continue
            out.append({"role": m.get("role"), "text": "\n\n".join(parts.get(mid, [])).strip(),
                        "ts": _ts((m.get("time") or {}).get("created")),
                        "at": float((m.get("time") or {}).get("created") or 0) / 1000,
                        "done": bool((m.get("time") or {}).get("completed") or m.get("finish")),
                        "model": "/".join(x for x in (m.get("providerID"), m.get("modelID")) if x),
                        "tokens": m.get("tokens") or {}})
        return out

    def revision(self, ref: Ref) -> str:
        try:
            with _open(ref.db) as c:
                r = c.execute("select count(*), max(time_updated) from part where session_id = ?",
                              (ref.sid,)).fetchone()
        except sqlite3.Error:
            return ""
        return f"{ref.sid[-8:]}-{r[0]}-{r[1] or 0}"


# ---------- Hermes ----------
class HermesDB:
    def __init__(self, db: Path | None = None):
        self.db = Path(db) if db else Path.home() / ".hermes/state.db"

    def latest(self, path: str) -> str:
        if not self.db.is_file():
            return ""
        try:
            with _open(self.db) as c:
                r = c.execute("select id from sessions where cwd = ? and parent_session_id is null "
                              "order by coalesce(last_activity_at, started_at) desc limit 1", (str(path),)).fetchone()
        except sqlite3.Error:
            return ""
        return r[0] if r else ""

    def ref(self, path: str, sid: str = "") -> Ref | None:
        sid = valid_sid(sid) or self.latest(path)
        return Ref(self.db, sid) if sid else None

    def rows(self, ref: Ref) -> list[dict]:
        try:
            with _open(ref.db) as c:
                model = (c.execute("select model from sessions where id = ?", (ref.sid,)).fetchone() or [""])[0]
                msgs = c.execute("select role, content, timestamp, finish_reason from messages where session_id = ? "
                                 "order by id", (ref.sid,)).fetchall()
        except sqlite3.Error:
            return []
        out = []
        for role, content, ts, fin in msgs:
            if role not in ("user", "assistant"):
                continue                               # инструменты и система — не в ленту
            out.append({"role": role, "text": str(content or "").strip(), "ts": _ts(ts), "at": float(ts or 0),
                        "done": bool(fin),
                        "model": model or "", "tokens": {}})
        return out

    def revision(self, ref: Ref) -> str:
        try:
            with _open(ref.db) as c:
                r = c.execute("select transcript_revision, message_count, last_activity_at from sessions "
                              "where id = ?", (ref.sid,)).fetchone()
        except sqlite3.Error:
            return ""
        return f"{ref.sid[-8:]}-{r[0] if r else 0}-{r[1] if r else 0}-{r[2] if r else 0}"


# ---------- общее для обеих ----------
def items(rows: list[dict]) -> list[dict]:
    """Лента: сообщения с текстом (ход с одними инструментами — без текста — не показываем)."""
    return [{"role": r["role"], "text": r["text"], "ts": r["ts"]} for r in rows
            if r["role"] in ("user", "assistant") and r["text"]]


def status(rows: list[dict]) -> dict:
    """Фаза хода, как ``pi_journal.status``: последнее — вопрос человека или незавершённый ответ → ``working``."""
    if not rows:
        return {"phase": "idle"}
    last = rows[-1]
    if last["role"] == "user" or (last["role"] == "assistant" and not last["done"]):
        return {"phase": "working"}
    return {"phase": "done"}


def answers_at(rows: list[dict]) -> list[tuple[float, str]]:
    """Ответы с текстом и временем (секунды) — для пересылки в Telegram, как у Pi."""
    return [(r.get("at") or 0.0, r["text"]) for r in rows if r["role"] == "assistant" and r["text"] and r["done"]]


def last_model(rows: list[dict]) -> str:
    return next((r["model"] for r in reversed(rows) if r["role"] == "assistant" and r["model"]), "")
