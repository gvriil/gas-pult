"""Задачи владельца (#203): чек-лист того, что решено и что нет, — с действием и привязкой к чату.

Решение владельца 14.11: «чтобы я понимал, какие задачи не решены и какие решены — выполнить команду, позвонить,
написать … сразу нажать, провалиться туда и продолжить работу … это для меня супер важно, чтобы не теряться».

Хранилище — ``<данные пульта>/tasks.json`` (0600), запись атомарная под файловым замком: задачи кладут панель, бот и
агенты (``gas-pult task add``) из разных процессов. Задача:

- ``title``; ``status``: todo (не начато) · doing (в работе) · waiting (ждёт владельца) · done (выполнено);
- ``kind`` — тип действия и его поля: command (``cmd``) · call (``phone``) · write (``to``, ``draft``) · meeting
  (``with``, ``when``) · decision (``question``, ``options``) · check (``link``) · other;
- ``next`` — что сделать дальше (обязательно для невыполненных); ``chat`` — окно, ``sid`` — разговор (окно может
  смениться при перезапуске — ищем по разговору); ``link`` — источник (issue, PR, документ);
- ``by`` — кто поставил (owner / agent / имя окна); ``created``, ``done_at``.

Порядок: «ждёт владельца» — первыми, потом в работе и не начатые (новые сверху), выполненные — в конце.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import secrets
import threading
import time
from pathlib import Path

from gas_pult.config import write_private

STATUSES = ("todo", "doing", "waiting", "done")
KINDS = {"command": ("cmd",), "call": ("phone",), "write": ("to", "draft"), "meeting": ("with", "when"),
         "decision": ("question", "options"), "check": ("link",), "other": ()}
TITLES = {"command": "Выполнить команду", "call": "Позвонить", "write": "Написать", "meeting": "Встреча",
          "decision": "Решение", "check": "Проверить", "other": "Другое"}
STATUS_TITLES = {"todo": "не начато", "doing": "в работе", "waiting": "ждёт вас", "done": "выполнено"}
ORDER = {"waiting": 0, "doing": 1, "todo": 2, "done": 3}
MAX = 500                       # больше — самые старые выполненные уходят
LIMITS = {"title": 200, "next": 300, "cmd": 2000, "phone": 40, "to": 120, "draft": 4000, "with": 200, "when": 80,
          "question": 500, "link": 500, "chat": 20, "sid": 36, "by": 60}


def clean(d: dict) -> dict:
    """Только известные поля, строки — обрезанные; варианты решения — до 8 строк."""
    out = {}
    for k, n in LIMITS.items():
        if k in d and d[k] is not None:
            out[k] = " ".join(str(d[k]).split())[:n] if k not in ("cmd", "draft") else str(d[k])[:n].strip()
    if "options" in d:
        out["options"] = [str(x).strip()[:200] for x in (d["options"] or []) if str(x).strip()][:8]
    return out


def check(t: dict) -> dict:
    if not t.get("title"):
        raise ValueError("нужен заголовок задачи")
    if t.get("kind", "other") not in KINDS:
        raise ValueError("тип: " + ", ".join(KINDS))
    if t.get("status", "todo") not in STATUSES:
        raise ValueError("статус: " + ", ".join(STATUSES))
    if t.get("status") != "done" and not t.get("next"):
        raise ValueError("для невыполненной задачи нужно «что сделать дальше»")
    need = {"command": "cmd", "call": "phone", "decision": "question", "check": "link"}.get(t.get("kind"))
    if need and not t.get(need):
        raise ValueError(f"для типа «{TITLES[t['kind']]}» нужно поле {need}")
    if t.get("kind") == "decision" and len(t.get("options") or []) < 2:
        raise ValueError("для решения нужны хотя бы два варианта")
    return t


def order(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda t: (ORDER.get(t.get("status"), 9), -(t.get("done_at") or t.get("created") or 0)
                                        if t.get("status") == "done" else -(t.get("created") or 0)))


class Tasks:
    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock, self.lock = Path(path), clock, threading.Lock()

    @contextlib.contextmanager
    def _locked(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with open(self.path.with_name(f".{self.path.name}.lock"), "a") as fh:
                fcntl.flock(fh, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fh, fcntl.LOCK_UN)

    def _load(self) -> list[dict]:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [x for x in d if isinstance(x, dict) and x.get("id")] if isinstance(d, list) else []

    def _save(self, items: list[dict]):
        done = [x for x in items if x.get("status") == "done"]
        if len(items) > MAX and done:                       # лишнее — самые старые выполненные
            drop = {x["id"] for x in sorted(done, key=lambda x: x.get("done_at") or 0)[:len(items) - MAX]}
            items = [x for x in items if x["id"] not in drop]
        write_private(self.path, json.dumps(items, ensure_ascii=False))

    def list(self) -> list[dict]:
        return order(self._load())

    def etag(self) -> str:
        """Версия списка — по содержимому файла: не менялся — 304 без тела."""
        try:
            return '"' + hashlib.sha256(self.path.read_bytes()).hexdigest()[:16] + '"'
        except OSError:
            return '"empty"'

    def open_count(self) -> dict:
        items = self._load()
        return {"open": sum(x.get("status") != "done" for x in items),
                "waiting": sum(x.get("status") == "waiting" for x in items)}

    def add(self, d: dict, by: str = "owner") -> dict:
        t = clean(d)
        t.update(kind=d.get("kind") or "other", status=d.get("status") or "todo")
        t.setdefault("by", by)
        check(t)
        t.update(id=secrets.token_hex(4), created=self.clock())
        if t["status"] == "done":
            t["done_at"] = t["created"]
        with self._locked():
            items = self._load()
            items.append(t)
            self._save(items)
        return t

    def update(self, tid: str, d: dict) -> dict:
        with self._locked():
            items = self._load()
            t = next((x for x in items if x["id"] == tid), None)
            if not t:
                raise LookupError("задачи уже нет")
            new = {**t, **clean(d)}
            for k in ("kind", "status"):
                if d.get(k):
                    new[k] = d[k]
            check(new)
            if new["status"] == "done" and t.get("status") != "done":
                new["done_at"] = self.clock()
            if new["status"] != "done":
                new.pop("done_at", None)
            if "result" in d:                               # итог «Выполнить»: код и когда — без вывода
                new["result"] = {k: d["result"][k] for k in ("code", "at") if k in d["result"]}
            items[items.index(t)] = new
            self._save(items)
        return new

    def remove(self, tid: str) -> bool:
        with self._locked():
            items = self._load()
            keep = [x for x in items if x["id"] != tid]
            if len(keep) == len(items):
                return False
            self._save(keep)
        return True

    def get(self, tid: str) -> dict | None:
        return next((x for x in self._load() if x["id"] == tid), None)
