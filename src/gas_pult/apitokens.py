"""Токены API v1 для 1С, CRM и телефонии (решение владельца 22.11, правило «API с первого дня»).

Внешняя система ходит в ``/api/v1/<путь>`` с заголовком ``Authorization: Bearer <токен>``; права — таблица
``access.V1_*`` (белый список путей), данные — того, кто выпустил токен (владелец пульта или человек пространства).

- Выпуск — в «Настройки → Токены для 1С и CRM». Токен показывается один раз; в файле — только sha256.
- Права узкие: по умолчанию только чтение; запись (``write``) — отдельной галочкой. Группы путей — ``groups``.
- Срок — по умолчанию год; отзыв — сразу. ``seen`` — последнее использование.
- Журнал вызовов — ``api-tokens-log.jsonl`` (0600, ``flock``): время, id токена, метод, путь, код. Без тел запросов
  и без параметров (в них бывают имена и телефоны).

Файлы в папке данных: ``api_tokens.json`` и ``api-tokens-log.jsonl``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path

from gas_pult import store

PREFIX = "gpa_"
DAY = 86400
TERMS = (30, 90, 365, 730)              # срок в днях — выбор в панели; по умолчанию год
DEFAULT_DAYS = 365
TOKENS_MAX = 20                         # токенов на человека (вместе с отозванными не считаем)
LOG_MAX = 5 << 20                       # журнал больше 5 МБ — в ``.1`` (одна старая копия)
GROUPS = ("sessions", "tasks", "drafts", "send")
_ID = re.compile(r"^[0-9a-f]{12}$")
_SAFE_PATH = re.compile(r"[^A-Za-z0-9/_.-]")


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def bearer(header: str) -> str:
    """Токен из ``Authorization: Bearer …``; другое — пустая строка."""
    kind, _, tok = (header or "").strip().partition(" ")
    return tok.strip() if kind.lower() == "bearer" else ""


def public(rec: dict, now: float) -> dict:
    """Запись для панели: без хэша."""
    st = ("revoked" if rec.get("revoked") else "expired" if float(rec.get("expires") or 0) <= now else "active")
    return {k: rec.get(k) for k in ("id", "name", "write", "groups", "created", "expires", "seen", "revoked")} | \
        {"state": st}


class Tokens:
    """Токены: id, hash, name, by (кто выпустил), space ("" — владелец пульта), write, groups, created, expires,
    revoked, seen. Файл — 0600, под ``store.locked`` (бот и панель — разные процессы)."""

    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock = Path(path), clock

    def _load(self) -> list[dict]:
        return [x for x in store.load(self.path, list) if isinstance(x, dict) and x.get("id")]

    def create(self, by: int, space: str = "", name: str = "", write: bool = False, days: int = DEFAULT_DAYS,
               groups=None) -> dict:
        """Новый токен. Ответ с ``token`` — единственный раз, когда токен виден целиком."""
        name = " ".join(str(name or "").split())[:60]
        if not name:
            raise ValueError("назовите токен: например, «1С Бухгалтерия» — чтобы потом знать, что отзывать")
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = DEFAULT_DAYS
        if days not in TERMS:
            raise ValueError("срок — 30, 90, 365 или 730 дней")
        gs = [g for g in GROUPS if g in (groups if groups is not None else GROUPS)]
        if not write:
            gs = [g for g in gs if g != "send"]          # отправка сообщения — только запись
        if not gs:
            raise ValueError("выберите хотя бы одну группу прав")
        tok = PREFIX + secrets.token_urlsafe(32)
        now = self.clock()
        rec = {"id": secrets.token_hex(6), "hash": digest(tok), "name": name, "by": int(by), "space": str(space or ""),
               "write": bool(write), "groups": gs, "created": now, "expires": now + days * DAY, "revoked": None,
               "seen": None}
        with store.locked(self.path):
            items = self._load()
            live = [x for x in items if x.get("by") == rec["by"] and x.get("space") == rec["space"]
                    and not x.get("revoked")]
            if len(live) >= TOKENS_MAX:
                raise ValueError(f"не больше {TOKENS_MAX} токенов — отзовите ненужные")
            items.append(rec)
            store.save(self.path, items, ensure_ascii=False)
        return {**public(rec, now), "token": tok}

    def mine(self, by: int, space: str = "") -> list[dict]:
        now = self.clock()
        out = [public(x, now) for x in self._load() if x.get("by") == by and x.get("space") == (space or "")]
        return sorted(out, key=lambda x: -float(x.get("created") or 0))

    def revoke(self, by: int, space: str, tid: str) -> dict:
        """Отозвать свой токен. Чужой и несуществующий — одинаково «не найден»."""
        with store.locked(self.path):
            items = self._load()
            rec = next((x for x in items if _ID.match(str(tid or "")) and x.get("id") == tid and x.get("by") == by
                        and x.get("space") == (space or "")), None)
            if not rec:
                raise LookupError("токен не найден")
            if not rec.get("revoked"):
                rec["revoked"] = self.clock()
                store.save(self.path, items, ensure_ascii=False)
        return {"ok": True}

    def check(self, token: str) -> dict | None:
        """Действующий токен → его запись (и отметка «последнее использование»); иначе None. Хэш сравнивается со
        всеми записями за постоянное время (без раннего выхода)."""
        if not token or not token.startswith(PREFIX) or len(token) > 100:
            return None
        h = digest(token)
        with store.locked(self.path):
            items = self._load()
            rec = None
            for x in items:
                if secrets.compare_digest(str(x.get("hash", "")), h):
                    rec = x
            now = self.clock()
            if not rec or rec.get("revoked") or float(rec.get("expires") or 0) <= now:
                return None
            if now - float(rec.get("seen") or 0) > 60:   # отметка не чаще раза в минуту — без записи на каждый вызов
                rec["seen"] = now
                store.save(self.path, items, ensure_ascii=False)
        return dict(rec)


class Guard:
    """Подбор токена: больше ``LIMIT`` неверных токенов с одного адреса за ``WINDOW`` секунд — 429 до конца окна."""

    LIMIT, WINDOW = 20, 60

    def __init__(self, clock=time.time):
        self.clock, self.fails = clock, {}

    def blocked(self, ip: str) -> bool:
        t0, n = self.fails.get(ip, (0.0, 0))
        return self.clock() - t0 < self.WINDOW and n >= self.LIMIT

    def fail(self, ip: str):
        now = self.clock()
        t0, n = self.fails.get(ip, (now, 0))
        self.fails[ip] = (t0, n + 1) if now - t0 < self.WINDOW else (now, 1)
        if len(self.fails) > 10000:                       # память не растёт без конца
            self.fails = {k: v for k, v in self.fails.items() if now - v[0] < self.WINDOW}


class Log:
    """Журнал вызовов ``/api/v1``: одна строка JSON на вызов. Только время, токен, метод, путь, код."""

    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock = Path(path), clock

    def write(self, tid: str, method: str, path: str, code: int):
        line = json.dumps({"t": round(self.clock(), 3), "id": str(tid or "")[:12], "m": str(method)[:7],
                           "p": _SAFE_PATH.sub("", str(path).split("?", 1)[0])[:80], "c": int(code)})
        try:
            with store.locked(self.path):
                if self.path.exists() and self.path.stat().st_size > LOG_MAX:
                    os.replace(self.path, self.path.with_name(self.path.name + ".1"))
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError as e:                              # журнал не ломает ответ — но ошибку видно в логах службы
            print("api-tokens-log:", e, flush=True)

    def read(self, tid: str | None = None, limit: int = 200) -> list[dict]:
        try:
            rows = [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()]
        except (OSError, ValueError):
            return []
        return [r for r in rows if tid is None or r.get("id") == tid][-limit:]
