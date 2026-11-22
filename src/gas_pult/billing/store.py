"""Хранилище платежей: SQLite (``billing.sqlite3`` в папке данных пульта, права 0600, режим WAL).

Правила, которые держит сама база (триггеры), а не только код:
- журнал ``journal`` — только добавление: UPDATE и DELETE строк — ошибка; исправление — встречной записью
  (``reverses`` — номер исправляемой строки, сумма с обратным знаком);
- строки счёта ``items`` не меняются и не удаляются; счёт не удаляется;
- у счёта меняются только статус и даты, статус — только по допустимым переходам ``TRANSITIONS``;
- ключ операции ``journal.key`` уникален: повтор операции с тем же ключом возвращает прежний итог, а не дублирует.
"""

import json
import os
import re
import sqlite3
import time
from pathlib import Path

from . import money

FILE = "billing.sqlite3"
PERIODS = ("once", "month", "year")
STATUSES = ("draft", "issued", "paid", "void")
# Допустимые переходы статуса счёта. Оплаченный счёт аннулируется только встречными записями (оплата и выставление).
TRANSITIONS = {"draft": ("issued", "void"), "issued": ("paid", "void"), "paid": ("void",), "void": ()}
KEY_RE = re.compile(r"[A-Za-z0-9_.:-]{8,80}")
PREFIX = "GP"                       # номер счёта: GP-2026-00001

_ALLOWED = " OR ".join(f"(OLD.status = '{a}' AND NEW.status = '{b}')" for a, bs in TRANSITIONS.items() for b in bs)
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS plans (
  code TEXT PRIMARY KEY CHECK (length(code) BETWEEN 2 AND 40),
  title TEXT NOT NULL,
  amount INTEGER NOT NULL CHECK (typeof(amount) = 'integer' AND amount >= 0),
  currency TEXT NOT NULL CHECK (length(currency) = 3),
  period TEXT NOT NULL CHECK (period IN ('once', 'month', 'year')),
  created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY,
  number TEXT NOT NULL UNIQUE,
  space TEXT NOT NULL DEFAULT '',
  client TEXT NOT NULL,
  currency TEXT NOT NULL CHECK (length(currency) = 3),
  total INTEGER NOT NULL CHECK (typeof(total) = 'integer' AND total >= 0),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'issued', 'paid', 'void')),
  created INTEGER NOT NULL, due_days INTEGER NOT NULL DEFAULT 14,
  issued INTEGER, paid INTEGER, voided INTEGER
);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  invoice INTEGER NOT NULL REFERENCES invoices(id),
  title TEXT NOT NULL,
  plan TEXT,
  qty INTEGER NOT NULL CHECK (typeof(qty) = 'integer' AND qty > 0),
  unit INTEGER NOT NULL CHECK (typeof(unit) = 'integer' AND unit >= 0),
  amount INTEGER NOT NULL CHECK (typeof(amount) = 'integer' AND amount = qty * unit)
);
CREATE TABLE IF NOT EXISTS journal (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  key TEXT NOT NULL UNIQUE,
  op TEXT NOT NULL CHECK (op IN ('plan', 'create', 'issue', 'payment', 'void', 'reversal')),
  invoice INTEGER REFERENCES invoices(id),
  amount INTEGER NOT NULL DEFAULT 0 CHECK (typeof(amount) = 'integer'),
  currency TEXT NOT NULL DEFAULT '',
  actor TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  reverses INTEGER REFERENCES journal(seq),
  data TEXT NOT NULL DEFAULT '{{}}'
);
CREATE TABLE IF NOT EXISTS webhook_seen (sig TEXT PRIMARY KEY, ts INTEGER NOT NULL);
CREATE TRIGGER IF NOT EXISTS journal_no_update BEFORE UPDATE ON journal
  BEGIN SELECT RAISE(ABORT, 'журнал только для добавления: исправление — встречной записью'); END;
CREATE TRIGGER IF NOT EXISTS journal_no_delete BEFORE DELETE ON journal
  BEGIN SELECT RAISE(ABORT, 'журнал только для добавления: удалять нельзя'); END;
CREATE TRIGGER IF NOT EXISTS items_no_update BEFORE UPDATE ON items
  BEGIN SELECT RAISE(ABORT, 'строки счёта не меняются'); END;
CREATE TRIGGER IF NOT EXISTS items_no_delete BEFORE DELETE ON items
  BEGIN SELECT RAISE(ABORT, 'строки счёта не удаляются'); END;
CREATE TRIGGER IF NOT EXISTS plans_no_update BEFORE UPDATE ON plans
  BEGIN SELECT RAISE(ABORT, 'тариф не меняется: новая цена — новый код'); END;
CREATE TRIGGER IF NOT EXISTS plans_no_delete BEFORE DELETE ON plans
  BEGIN SELECT RAISE(ABORT, 'тариф не удаляется'); END;
CREATE TRIGGER IF NOT EXISTS invoices_no_delete BEFORE DELETE ON invoices
  BEGIN SELECT RAISE(ABORT, 'счёт не удаляется: аннулируйте'); END;
CREATE TRIGGER IF NOT EXISTS invoices_fixed BEFORE UPDATE ON invoices
  WHEN NEW.number IS NOT OLD.number OR NEW.space IS NOT OLD.space OR NEW.client IS NOT OLD.client
    OR NEW.currency IS NOT OLD.currency OR NEW.total IS NOT OLD.total OR NEW.created IS NOT OLD.created
  BEGIN SELECT RAISE(ABORT, 'у счёта меняются только статус и даты'); END;
CREATE TRIGGER IF NOT EXISTS invoices_status BEFORE UPDATE OF status ON invoices
  WHEN NEW.status IS NOT OLD.status AND NOT ({_ALLOWED})
  BEGIN SELECT RAISE(ABORT, 'недопустимый переход статуса счёта'); END;
"""


class Conflict(ValueError):
    """Ключ операции уже использован для другой операции."""


def path(data: Path) -> Path:
    return Path(data) / FILE


def connect(data: Path) -> sqlite3.Connection:
    """Соединение: файл 0600 (создаётся до SQLite), WAL, внешние ключи, схема. Транзакции — явные (``tx``)."""
    p = path(data)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        os.close(os.open(p, os.O_CREAT | os.O_WRONLY, 0o600))
    con = sqlite3.connect(p, isolation_level=None, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA synchronous=FULL")              # деньги: надёжность важнее скорости записи
    con.executescript(SCHEMA)
    for suf in ("", "-wal", "-shm"):                     # файлы WAL создаёт SQLite — права те же
        f = Path(str(p) + suf)
        if f.exists() and f.stat().st_mode & 0o777 != 0o600:
            f.chmod(0o600)
    return con


class tx:
    """``with tx(con):`` — BEGIN IMMEDIATE … COMMIT, при ошибке ROLLBACK (одна запись за раз, без гонок)."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, et, e, tb):
        self.con.execute("ROLLBACK" if et else "COMMIT")
        return False


def key_of(key) -> str:
    k = str(key or "")
    if not KEY_RE.fullmatch(k):
        raise ValueError("нужен ключ операции: 8–80 знаков, латиница, цифры, _.:-")
    return k


def _text(v, name: str, n: int = 120, empty: bool = False) -> str:
    s = " ".join(str(v or "").split())[:n]
    if not s and not empty:
        raise ValueError("пусто: " + name)
    return s


def _seen(con, key: str, op: str, invoice=None):
    """Повтор операции: строка журнала с этим ключом. Тот же ключ на другую операцию — ``Conflict``."""
    r = con.execute("SELECT * FROM journal WHERE key = ?", (key,)).fetchone()
    if r and (r["op"] != op or (invoice is not None and r["invoice"] != invoice)):
        raise Conflict("ключ операции уже использован для другой операции")
    return r


def _log(con, key, op, *, invoice=None, amount=0, cur="", actor="", reason="", reverses=None, data=None) -> int:
    money.check(amount, signed=True)
    c = con.execute("INSERT INTO journal (ts, key, op, invoice, amount, currency, actor, reason, reverses, data) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (int(time.time()), key, op, invoice, amount, cur, actor, reason, reverses,
                     json.dumps(data or {}, ensure_ascii=False, sort_keys=True)))
    return c.lastrowid


# ---------- тарифы ----------

def plans(con) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM plans ORDER BY created, code")]


def add_plan(con, code: str, title: str, amount: int, cur: str, period: str, *, key: str, actor: str = "") -> dict:
    """Новый тариф. Тариф не меняется: другая цена — другой код. Повтор с тем же ключом — тот же тариф."""
    key = key_of(key)
    code = str(code or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,39}", code):
        raise ValueError("код тарифа: 2–40 знаков, латиница, цифры, _-")
    if period not in PERIODS:
        raise ValueError("период: " + ", ".join(PERIODS))
    title, cur, amount = _text(title, "название"), money.currency(cur), money.check(amount)
    with tx(con):
        if r := _seen(con, key, "plan"):
            return dict(con.execute("SELECT * FROM plans WHERE code = ?", (json.loads(r["data"])["code"],)).fetchone())
        if con.execute("SELECT 1 FROM plans WHERE code = ?", (code,)).fetchone():
            raise Conflict("тариф с таким кодом уже есть: цену не меняем, заведите новый код")
        con.execute("INSERT INTO plans VALUES (?, ?, ?, ?, ?, ?)", (code, title, amount, cur, period, int(time.time())))
        _log(con, key, "plan", amount=amount, cur=cur, actor=actor, data={"code": code, "period": period})
    return dict(con.execute("SELECT * FROM plans WHERE code = ?", (code,)).fetchone())


# ---------- счета ----------

def _number(con) -> str:
    year = time.strftime("%Y", time.gmtime())
    n = con.execute("SELECT COUNT(*) FROM invoices WHERE number LIKE ?", (f"{PREFIX}-{year}-%",)).fetchone()[0]
    return f"{PREFIX}-{year}-{n + 1:05d}"


def invoice(con, iid: int) -> dict:
    r = con.execute("SELECT * FROM invoices WHERE id = ?", (int(iid),)).fetchone()
    if not r:
        raise LookupError("нет такого счёта")
    d = dict(r)
    d["items"] = [dict(x) for x in con.execute("SELECT title, plan, qty, unit, amount FROM items WHERE invoice = ? "
                                               "ORDER BY id", (d["id"],))]
    d["journal"] = [dict(x) for x in con.execute("SELECT seq, ts, op, amount, currency, actor, reason, reverses "
                                                 "FROM journal WHERE invoice = ? ORDER BY seq", (d["id"],))]
    d["balance"] = balance(con, d["id"])
    d["next"] = list(TRANSITIONS[d["status"]])
    return d


def invoices(con, limit: int = 200) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT id, number, space, client, currency, total, status, created, issued,"
                                         " paid, voided FROM invoices ORDER BY id DESC LIMIT ?", (int(limit),))]


def balance(con, iid: int) -> int:
    """К оплате: выставлено − оплачено, по журналу (встречные записи учтены знаком)."""
    r = con.execute("SELECT COALESCE(SUM(CASE WHEN op IN ('issue') OR (op = 'reversal' AND json_extract(data, '$.of') ="
                    " 'issue') THEN amount ELSE 0 END), 0) - COALESCE(SUM(CASE WHEN op = 'payment' OR (op = 'reversal'"
                    " AND json_extract(data, '$.of') = 'payment') THEN amount ELSE 0 END), 0) FROM journal "
                    "WHERE invoice = ?", (iid,)).fetchone()
    return int(r[0])


def create(con, client: str, cur: str, lines: list, *, key: str, space: str = "", due_days: int = 14,
           actor: str = "") -> dict:
    """Черновик счёта. ``lines`` — [{"title", "qty", "unit"}] или [{"plan": код, "qty"}]; суммы — целые центы."""
    key, client, space = key_of(key), _text(client, "клиент"), _text(space, "пространство", 60, empty=True)
    cur = money.currency(cur)
    if not isinstance(lines, list) or not 1 <= len(lines) <= 50:
        raise ValueError("в счёте от 1 до 50 строк")
    if isinstance(due_days, bool) or not isinstance(due_days, int) or not 0 <= due_days <= 365:
        raise ValueError("срок оплаты — от 0 до 365 дней")
    with tx(con):
        if r := _seen(con, key, "create"):
            return invoice(con, r["invoice"])
        rows = []
        for x in lines:
            if not isinstance(x, dict):
                raise ValueError("строка счёта — объект")
            qty = x.get("qty", 1)
            if x.get("plan"):
                p = con.execute("SELECT * FROM plans WHERE code = ?", (str(x["plan"]),)).fetchone()
                if not p:
                    raise ValueError("нет такого тарифа: " + str(x["plan"])[:40])
                if p["currency"] != cur:
                    raise ValueError("валюта тарифа не совпадает с валютой счёта")
                rows.append((p["title"], p["code"], qty, p["amount"], money.line(qty, p["amount"])))
            else:
                unit = money.check(x.get("unit"))
                rows.append((_text(x.get("title"), "строка счёта"), None, qty, unit, money.line(qty, unit)))
        total = money.check(sum(r[4] for r in rows))
        c = con.execute("INSERT INTO invoices (number, space, client, currency, total, created, due_days) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)", (_number(con), space, client, cur, total, int(time.time()),
                                                         due_days))
        iid = c.lastrowid
        con.executemany("INSERT INTO items (invoice, title, plan, qty, unit, amount) VALUES (?, ?, ?, ?, ?, ?)",
                        [(iid, *r) for r in rows])
        _log(con, key, "create", invoice=iid, cur=cur, actor=actor, data={"total": total, "lines": len(rows)})
    return invoice(con, iid)


def _move(con, iid: int, to: str, key: str, op: str, *, actor: str, reason: str = "", extra=None) -> dict:
    """Общий шаг: повтор по ключу → прежний итог; иначе проверка перехода, запись журнала, новый статус."""
    key = key_of(key)
    with tx(con):
        if _seen(con, key, op, int(iid)):
            return invoice(con, iid)
        inv = con.execute("SELECT * FROM invoices WHERE id = ?", (int(iid),)).fetchone()
        if not inv:
            raise LookupError("нет такого счёта")
        if to not in TRANSITIONS[inv["status"]]:
            raise ValueError(f"счёт «{inv['status']}» нельзя перевести в «{to}»")
        now, cur = int(time.time()), inv["currency"]
        if op == "issue":
            _log(con, key, "issue", invoice=iid, amount=inv["total"], cur=cur, actor=actor)
            con.execute("UPDATE invoices SET status = 'issued', issued = ? WHERE id = ?", (now, iid))
        elif op == "payment":
            _log(con, key, "payment", invoice=iid, amount=inv["total"], cur=cur, actor=actor, reason=reason,
                 data=extra)
            con.execute("UPDATE invoices SET status = 'paid', paid = ? WHERE id = ?", (now, iid))
        else:                                             # аннулирование: встречная запись к каждой сумме
            head = _log(con, key, "void", invoice=iid, cur=cur, actor=actor, reason=reason)
            done = {r["reverses"] for r in con.execute("SELECT reverses FROM journal WHERE invoice = ? AND "
                                                       "reverses IS NOT NULL", (iid,))}
            for r in con.execute("SELECT seq, op, amount FROM journal WHERE invoice = ? AND op IN ('issue', 'payment')"
                                 " ORDER BY seq", (iid,)).fetchall():
                if r["seq"] not in done:
                    _log(con, f"{key}#{r['seq']}", "reversal", invoice=iid, amount=-r["amount"], cur=cur, actor=actor,
                         reason=reason, reverses=r["seq"], data={"of": r["op"], "void": head})
            con.execute("UPDATE invoices SET status = 'void', voided = ? WHERE id = ?", (now, iid))
    return invoice(con, iid)


def issue(con, iid: int, *, key: str, actor: str = "") -> dict:
    return _move(con, iid, "issued", key, "issue", actor=actor)


def mark_paid(con, iid: int, *, key: str, reason: str, actor: str = "", ref: str = "") -> dict:
    """Оплата вручную — только с основанием (что подтверждает оплату: выписка, платёжка)."""
    reason = _text(reason, "основание оплаты", 300)
    return _move(con, iid, "paid", key, "payment", actor=actor, reason=reason,
                 extra={"manual": True, **({"ref": _text(ref, "ref", 80)} if ref else {})})


def void(con, iid: int, *, key: str, reason: str, actor: str = "") -> dict:
    return _move(con, iid, "void", key, "void", actor=actor, reason=_text(reason, "причина", 300))


def remember_webhook(con, sig: str) -> bool:
    """Защита от повтора вебхука: True — подпись видим впервые; False — уже была (повтор)."""
    with tx(con):
        c = con.execute("INSERT OR IGNORE INTO webhook_seen (sig, ts) VALUES (?, ?)", (sig, int(time.time())))
        con.execute("DELETE FROM webhook_seen WHERE ts < ?", (int(time.time()) - 7 * 86400,))   # неделя — с запасом
    return c.rowcount == 1
