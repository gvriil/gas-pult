"""События продукта и воронка (аудит 22.11: «не экономим на аналитике событий»): ``<данные>/product-events.jsonl``
(0600), одна строка — одно событие. Это не журнал отладки ``chat-events.jsonl`` (chatlog.py) — тот про путь одного
сообщения и живёт 30 дней; здесь — что человек сделал, для воронки, ``keep_days`` дней (400 — на год с запасом).

Поля строки: ``t`` (время), ``ev`` (событие), ``v`` (версия схемы), ``u`` (отпечаток человека), ``sp`` (пространство
или ""), иногда ``via`` (способ входа или откуда решение — слово из короткого списка). Отпечаток — sha256 Telegram ID
с солью из ``product-salt`` (0600, в папке данных): по журналу человека не узнать, а соль не уходит из сервера.
Текстов сообщений, имён, адресов, устройств и IP в журнале нет.

События: ``login`` (успешный вход любым способом), ``send`` (сообщение человека агенту), ``first_reply`` (первый ответ
агента этому человеку — один раз на человека; кто уже получил — ``product-seen.json``), ``yes`` / ``no`` («Да» / «Нет»
в «Ждут вашего Да»: черновики коннекторов, мост, вопросы агента в чате, брифинг).

Бот и панель пишут в один файл под ``flock``. Журнал никогда не ломает работу: ошибка записи — строка в stderr.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = 1
KEEP_DAYS = 400
EVENTS = ("login", "send", "first_reply", "yes", "no")
STEPS = ("login", "first_reply", "yes")              # шаги воронки: вошёл → получил ответ → сказал «Да»
FILE, SALT, SEEN = "product-events.jsonl", "product-salt", "product-seen.json"
_VIA = re.compile(r"^[a-z][a-z0-9_-]{0,15}$")         # способ входа / источник решения — короткое слово, не текст
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")

# Ключи пунктов вопроса Claude Code (humanize.OPTIONS) → «Да» / «Нет». Остальное («Подробнее», «Своими словами») — нет.
YES_KEYS = {"allow", "continue", "trust-yes", "plan-manual"}
NO_KEYS = {"deny", "plan-keep", "cancel"}


def choice(ask: dict | None, n: str = "", key: str = "") -> str | None:
    """Какой пункт вопроса агента выбрали: "yes" / "no" / None. ``ask`` — ``humanize.parse`` экрана до нажатия;
    ``n`` — номер пункта, ``key`` — клавиша (Enter, Escape)."""
    if not ask:
        return None
    want = {"n": str(n)} if n else {"key": key} if key else None
    if not want:
        return None
    for o in ask.get("options") or []:
        send = {k: str(v) for k, v in (o.get("send") or {}).items() if k in ("n", "key")}
        if send != want:
            continue
        k = str(o.get("key") or "")
        if k in YES_KEYS or k.startswith("yes"):
            return "yes"
        if k in NO_KEYS or k.startswith("no"):
            return "no"
        return None
    return None


class Funnel:
    def __init__(self, data: Path, keep_days: int | None = None, clock=time.time):
        self.data, self.clock = Path(data), clock
        self.path = self.data / FILE
        self.keep_days = int(keep_days) if keep_days and int(keep_days) > 0 else KEEP_DAYS
        self.lock = threading.Lock()
        self.pruned = 0.0
        self._salt: bytes | None = None
        self._replied: set[str] = set()              # кому первый ответ уже записан (кэш этого процесса)
        self._seen_at, self._seen_d = 0.0, {}       # кэш product-seen.json (sent_at), 30 с

    # ---------- отпечаток человека ----------
    def salt(self) -> bytes:
        if self._salt is None:
            p = self.data / SALT
            try:
                self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(secrets.token_hex(32))
            except FileExistsError:
                pass
            self._salt = p.read_bytes().strip()
        return self._salt

    def who(self, uid) -> str:
        """Отпечаток человека: 16 знаков sha256(соль + ID). Без соли (её файл) ID по отпечатку не подобрать."""
        return hashlib.sha256(self.salt() + b":" + str(int(uid)).encode()).hexdigest()[:16]

    # ---------- запись ----------
    def event(self, ev: str, uid, sp: str | None = "", via: str = "") -> dict | None:
        if ev not in EVENTS or uid is None:
            return None
        try:
            rec = {"t": round(self.clock(), 3), "ev": ev, "v": SCHEMA, "u": self.who(uid),
                   "sp": sp if isinstance(sp, str) and _SLUG.match(sp) else ""}
            if via and _VIA.match(via):
                rec["via"] = via
            self._append(json.dumps(rec, ensure_ascii=False) + "\n", rec["t"])
        except (OSError, ValueError, TypeError) as e:
            print(f"{FILE}: {e}", file=sys.stderr, flush=True)
            return None
        return rec

    def _append(self, line: str, now: float):
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.lock:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                f.write(line)
                f.flush()
                if now - self.pruned > 86400:          # раз в сутки — срезать старше keep_days
                    self.pruned = now
                    f.seek(0)
                    keep = [x for x in f.readlines() if _t(x) >= now - self.keep_days * 86400]
                    f.seek(0)
                    f.truncate()
                    f.writelines(keep)

    def login(self, uid, sp: str | None = "", via: str = "") -> dict | None:
        return self.event("login", uid, sp, via)

    def decide(self, uid, yes: bool, sp: str | None = "", via: str = "") -> dict | None:
        return self.event("yes" if yes else "no", uid, sp, via)

    def send(self, uid, sp: str | None = "", via: str = "") -> dict | None:
        """Сообщение человека агенту; запоминаем время — ответ после него будет «первым ответом»."""
        rec = self.event("send", uid, sp, via)
        if rec and rec["u"] not in self._replied:
            self._seen(lambda d: d.setdefault(rec["u"], {}).setdefault("sent", rec["t"]))
            self._seen_at = 0.0                       # своё сообщение — видно ответу сразу, без ожидания кэша
        return rec

    def replied(self, uid, sp: str | None = "", via: str = "") -> dict | None:
        """Агент ответил человеку: событие ``first_reply`` — только в первый раз на человека."""
        if uid is None:
            return None
        try:
            u = self.who(uid)
        except (OSError, ValueError, TypeError):
            return None
        if u in self._replied:
            return None
        first = []

        def mark(d):
            if not d.get(u, {}).get("replied"):
                d.setdefault(u, {})["replied"] = round(self.clock(), 3)
                first.append(1)
        if not self._seen(mark):
            return None
        self._replied.add(u)
        return self.event("first_reply", uid, sp, via) if first else None

    def sent_at(self, uid) -> float | None:
        """Когда человек впервые написал агенту, если ответа ему ещё не было (иначе None). Кэш файла — 30 с."""
        try:
            u = self.who(uid)
        except (OSError, ValueError, TypeError):
            return None
        if u in self._replied:
            return None
        now = time.time()
        if now - self._seen_at > 30:
            self._seen_at, self._seen_d = now, self._seen(None) or {}
        rec = self._seen_d.get(u) or {}
        if rec.get("replied"):
            self._replied.add(u)
            return None
        return rec.get("sent")

    def answered(self, uid, items: list[dict], sp: str | None = "") -> dict | None:
        """Панель показала человеку переписку: есть ответ агента после его первого сообщения — ``first_reply``.
        ``items`` — ``history`` журнала (``ts`` — «ГГГГ-ММ-ДД ЧЧ:ММ» UTC)."""
        if uid is None or not items or (at := self.sent_at(uid)) is None:
            return None
        since = datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%d %H:%M")
        if any(it.get("role") == "assistant" and not it.get("note") and str(it.get("ts") or "") >= since
               for it in items):
            return self.replied(uid, sp, "panel")
        return None

    def _seen(self, change) -> dict | bool:
        """Прочитать (``change`` = None) или поменять под замком ``product-seen.json``: отпечаток → sent/replied."""
        p = self.data / SEEN
        try:
            self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(p, os.O_RDWR | os.O_CREAT, 0o600)
            with os.fdopen(fd, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    d = json.loads(f.read() or "{}")
                except ValueError:
                    d = {}
                if change is None:
                    return d if isinstance(d, dict) else {}
                change(d)
                f.seek(0)
                f.truncate()
                f.write(json.dumps(d))
            return True
        except OSError as e:
            print(f"{SEEN}: {e}", file=sys.stderr, flush=True)
            return False

    # ---------- чтение ----------
    def read(self) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for x in lines:
            try:
                r = json.loads(x)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("ev") in EVENTS:
                out.append(r)
        return out


def report(events: list[dict], days: int = 30, space: str | None = None, now: float | None = None) -> dict:
    """Воронка за ``days`` дней: людей на каждом шаге (каждый следующий — из тех, кто прошёл прошлый), конверсия
    к прошлому шагу и к первому, число событий и разбивка по дням (UTC). ``space`` — только это пространство
    ("" — без пространства, None — все)."""
    now = time.time() if now is None else now
    since = now - max(1, int(days)) * 86400
    evs = [e for e in events if float(e.get("t", 0)) >= since and (space is None or e.get("sp", "") == space)]
    who: dict[str, set] = {k: set() for k in EVENTS}
    counts = dict.fromkeys(EVENTS, 0)
    by_day: dict[str, dict[str, set]] = {}
    for e in evs:
        ev, u = e["ev"], str(e.get("u") or "")
        counts[ev] += 1
        if not u:
            continue
        who[ev].add(u)
        day = datetime.fromtimestamp(float(e["t"]), UTC).strftime("%Y-%m-%d")
        by_day.setdefault(day, {k: set() for k in EVENTS})[ev].add(u)
    steps, have = [], None
    for ev in STEPS:
        have = set(who[ev]) if have is None else have & who[ev]
        steps.append({"ev": ev, "people": len(have)})
    top = steps[0]["people"]
    for i, s in enumerate(steps):
        prev = steps[i - 1]["people"] if i else None
        s["conv"] = None if prev is None else (round(s["people"] / prev, 3) if prev else 0.0)
        s["of_first"] = round(s["people"] / top, 3) if top else 0.0
    return {"days": max(1, int(days)), "space": space, "steps": steps, "events": counts,
            "people": {k: len(v) for k, v in who.items()},
            "by_day": [{"day": d, **{k: len(v) for k, v in by_day[d].items()}} for d in sorted(by_day)]}


TITLES = {"login": "вошли", "first_reply": "получили ответ", "yes": "сказали «Да»"}


def text(r: dict) -> str:
    """Свод воронки для консоли."""
    sp = r.get("space")
    lines = [f"Воронка за {r['days']} дн." + (f" · пространство {sp}" if sp else " · без пространства" if sp == ""
                                              else " · все пространства")]
    for i, s in enumerate(r["steps"]):
        conv = "" if s["conv"] is None else f"  ({s['conv'] * 100:.0f}% от прошлого шага)"
        lines.append(f"  {i + 1}. {TITLES[s['ev']]:<15} {s['people']:>5}{conv}")
    e = r["events"]
    lines.append(f"Событий: входов {e['login']}, сообщений {e['send']}, «Да» {e['yes']}, «Нет» {e['no']}")
    if r["by_day"]:
        lines.append("По дням (людей): день        вход  ответ  «Да»  сообщ.")
        for d in r["by_day"]:
            lines.append(f"  {d['day']}  {d['login']:>5} {d['first_reply']:>6} {d['yes']:>5} {d['send']:>7}")
    else:
        lines.append("Событий за этот срок нет.")
    return "\n".join(lines)


def _t(line: str) -> float:
    try:
        return float(json.loads(line).get("t", 0))
    except (ValueError, AttributeError, TypeError):
        return 0.0
