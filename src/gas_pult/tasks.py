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

Порядок: по матрице Эйзенхауэра (решение владельца 14.11: «по срочности и важности»): поля ``urgent`` и ``important``
(да/нет) → квадрант 1 «Срочно и важно — сделать сейчас», 2 «Важно, не срочно — запланировать», 3 «Срочно, не важно —
быстро или делегировать», 4 «Не срочно и не важно — потом или убрать»; без оценки — «Не разобрано» (после первого).
Срок ``due`` (ГГГГ-ММ-ДД) прошёл — задача считается срочной. Внутри квадранта: «ждёт владельца», в работе, не начато
(новые сверху); выполненные — в конце.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import re
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
QUADRANTS = {1: "Срочно и важно — сделать сейчас", 2: "Важно, не срочно — запланировать",
             3: "Срочно, не важно — быстро или делегировать", 4: "Не срочно и не важно — потом или убрать",
             0: "Не разобрано — оцените срочность и важность"}
Q_ORDER = {1: 0, 0: 1, 2: 2, 3: 3, 4: 4}          # «не разобрано» — сразу после срочного и важного
MAX = 500                       # больше — самые старые выполненные уходят
LIMITS = {"title": 200, "next": 300, "cmd": 2000, "phone": 40, "to": 120, "draft": 4000, "with": 200, "when": 80,
          "question": 500, "link": 500, "chat": 20, "sid": 36, "by": 60, "due": 10}


def clean(d: dict) -> dict:
    """Только известные поля, строки — обрезанные; варианты решения — до 8 строк."""
    out = {}
    for k, n in LIMITS.items():
        if k in d and d[k] is not None:
            out[k] = " ".join(str(d[k]).split())[:n] if k not in ("cmd", "draft") else str(d[k])[:n].strip()
    for k in ("urgent", "important"):                    # да / нет / не оценено (None)
        if k in d:
            out[k] = yes(d[k])
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
    if t.get("due") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(t["due"])):
        raise ValueError("срок: ГГГГ-ММ-ДД")
    if t.get("kind") == "decision" and len(t.get("options") or []) < 2:
        raise ValueError("для решения нужны хотя бы два варианта")
    return t


def yes(v) -> bool | None:
    """«да/нет» из CLI, панели и JSON: true/yes/да/1 — да; false/no/нет/0 — нет; пусто — не оценено."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "y", "yes", "true", "да", "д", "on"):
        return True
    if s in ("0", "n", "no", "false", "нет", "н", "off"):
        return False
    raise ValueError("срочно / важно: yes или no")


def overdue(t: dict, today: str | None = None) -> bool:
    today = today or time.strftime("%Y-%m-%d")
    return bool(t.get("due")) and t.get("status") != "done" and str(t["due"]) < today


def quadrant(t: dict, today: str | None = None) -> int:
    """1–4 по срочности и важности; срок прошёл — срочно; не оценено — 0."""
    u, i = t.get("urgent"), t.get("important")
    if overdue(t, today):
        u = True
    if u is None and i is None:
        return 0
    return {(True, True): 1, (False, True): 2, (True, False): 3, (False, False): 4}[(bool(u), bool(i))]


def set_quadrant(d: dict, q) -> dict:
    """``--q 1..4`` → срочно и важно."""
    q = int(q)
    if q not in (1, 2, 3, 4):
        raise ValueError("квадрант: 1, 2, 3 или 4")
    return {**d, "urgent": q in (1, 3), "important": q in (1, 2)}


def order(items: list[dict]) -> list[dict]:
    """Выполненные — в конце; остальные — по квадрантам (1, не разобрано, 2, 3, 4), внутри — по статусу и новизне."""
    today = time.strftime("%Y-%m-%d")

    def key(t):
        if t.get("status") == "done":
            return (9, 0, -(t.get("done_at") or t.get("created") or 0))
        return (Q_ORDER[quadrant(t, today)], ORDER.get(t.get("status"), 9), -(t.get("created") or 0))
    return sorted(items, key=key)


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
        """По порядку; ``q`` — квадрант (0 — не оценено), ``overdue`` — срок прошёл."""
        today = time.strftime("%Y-%m-%d")
        return [{**x, "q": quadrant(x, today), "overdue": overdue(x, today)} for x in order(self._load())]

    def etag(self) -> str:
        """Версия списка — по содержимому файла: не менялся — 304 без тела."""
        try:
            return '"' + hashlib.sha256(self.path.read_bytes()).hexdigest()[:16] + '"'
        except OSError:
            return '"empty"'

    def open_count(self) -> dict:
        items = self._load()
        live = [x for x in items if x.get("status") != "done"]
        return {"open": len(live), "waiting": sum(x.get("status") == "waiting" for x in live),
                "q1": sum(quadrant(x) == 1 for x in live)}

    def add(self, d: dict, by: str = "owner") -> dict:
        if d.get("q"):
            d = set_quadrant(d, d["q"])
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
        if d.get("q"):
            d = set_quadrant(d, d["q"])
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
