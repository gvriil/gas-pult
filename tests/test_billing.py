"""Платежи без поставщика (billing/, владелец 22.11): центы и округление, журнал только на добавление,
идемпотентность, вебхук (подделка, время, повтор), права API, переходы статуса счёта."""

import json
import sqlite3
import time
from decimal import Decimal

import pytest
from test_people_login import call, server  # noqa: F401

from gas_pult.billing import money, provider, store

KEY = "k-0000001"


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path)
    yield c
    c.close()


def draft(con, key="new-0001", **kw):
    lines = kw.pop("lines", [{"title": "Пример услуги", "qty": 3, "unit": 333}])
    return store.create(con, "Клиент «Пример»", "EUR", lines, key=key, **kw)


# ---------- центы и округление ----------

def test_cents_no_float_and_explicit_rounding():
    assert money.to_minor("12.34", "eur") == 1234 and money.to_minor("12,5", "EUR") == 1250
    assert money.to_minor(Decimal("0.1") + Decimal("0.2"), "EUR") == 30           # не 0.30000000000000004
    assert money.to_minor(7, "JPY") == 7 and money.to_minor("1.234", "BHD") == 1234
    with pytest.raises(TypeError):
        money.to_minor(0.1, "EUR")                                                 # float — никогда
    with pytest.raises(ValueError):
        money.to_minor("1.005", "EUR")                                             # лишний знак без округления
    assert money.to_minor("1.005", "EUR", "half_up") == 101
    assert money.to_minor("1.005", "EUR", "half_even") == 100                     # банковское — к чётному
    assert money.to_minor("2.5", "JPY", "half_even") == 2 and money.to_minor("2.5", "JPY", "half_up") == 3
    with pytest.raises(KeyError):
        money.to_minor("1.005", "EUR", "up")                                       # округление — только из списка
    assert money.percent(1999, 2000, "half_up") == 400 and money.percent(1999, 2000, "half_even") == 400
    assert money.percent(25, 5000, "half_even") == 12 and money.percent(25, 5000, "half_up") == 13
    with pytest.raises(TypeError):
        money.check(1.0)
    with pytest.raises(ValueError):
        money.check(-1)
    assert money.check(-5, signed=True) == -5
    with pytest.raises(ValueError):
        money.check(money.MAX_MINOR + 1)
    with pytest.raises(ValueError):
        money.currency("XXX")
    assert money.fmt(123456, "EUR") == "1234.56 EUR" and money.fmt(-5, "EUR") == "-0.05 EUR"
    assert money.fmt(5, "JPY") == "5 JPY" and money.line(3, 333) == 999


def test_invoice_total_in_integer_cents(con):
    inv = draft(con, lines=[{"title": "A", "qty": 3, "unit": 333}, {"title": "B", "unit": 1}])
    assert inv["total"] == 1000 and isinstance(inv["total"], int)
    assert [x["amount"] for x in inv["items"]] == [999, 1]
    with pytest.raises(TypeError):
        draft(con, key="new-float", lines=[{"title": "A", "unit": 9.99}])
    with pytest.raises(ValueError):
        draft(con, key="new-zero", lines=[{"title": "A", "qty": 0, "unit": 1}])
    with pytest.raises(sqlite3.IntegrityError):                                   # и сама база не примет float
        con.execute("INSERT INTO plans VALUES ('x1', 'x', 9.5, 'EUR', 'month', 0)")


# ---------- журнал только на добавление ----------

def test_journal_append_only(con):
    inv = draft(con)
    store.issue(con, inv["id"], key="iss-0001")
    for sql in ("UPDATE journal SET amount = 1", "DELETE FROM journal", "UPDATE journal SET reason = 'x' WHERE seq = 1",
                "UPDATE items SET unit = 1", "DELETE FROM items", "DELETE FROM invoices",
                "UPDATE invoices SET total = 1"):
        with pytest.raises(sqlite3.DatabaseError):
            con.execute(sql)
    assert con.execute("SELECT COUNT(*) FROM journal").fetchone()[0] == 2


def test_void_is_reversal_not_edit(con):
    inv = draft(con)
    store.issue(con, inv["id"], key="iss-0001")
    store.mark_paid(con, inv["id"], key="pay-0001", reason="выписка банка №1")
    before = [dict(r) for r in con.execute("SELECT * FROM journal ORDER BY seq")]
    v = store.void(con, inv["id"], key="void-0001", reason="ошибка в сумме")
    after = [dict(r) for r in con.execute("SELECT * FROM journal ORDER BY seq")]
    assert after[:len(before)] == before                                         # прежние строки не тронуты
    rev = [r for r in after if r["op"] == "reversal"]
    assert sorted(r["amount"] for r in rev) == [-999, -999] and all(r["reverses"] for r in rev)
    assert v["status"] == "void" and v["balance"] == 0


# ---------- идемпотентность ----------

def test_idempotent_by_key(con):
    a = draft(con, key="same-0001")
    b = draft(con, key="same-0001")
    assert a["id"] == b["id"] and con.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 1
    store.issue(con, a["id"], key="iss-0001")
    store.issue(con, a["id"], key="iss-0001")                                    # повтор — тот же итог, без ошибки
    store.mark_paid(con, a["id"], key="pay-0001", reason="выписка")
    store.mark_paid(con, a["id"], key="pay-0001", reason="выписка")
    assert con.execute("SELECT COUNT(*) FROM journal WHERE op = 'payment'").fetchone()[0] == 1
    with pytest.raises(store.Conflict):
        store.void(con, a["id"], key="pay-0001", reason="другая операция тем же ключом")
    with pytest.raises(ValueError):
        draft(con, key="short")                                                  # ключ обязателен и не короткий
    p1 = store.add_plan(con, "demo-start", "Пример: Старт", 900, "EUR", "month", key="plan-0001")
    assert store.add_plan(con, "demo-start", "Пример: Старт", 900, "EUR", "month", key="plan-0001") == p1
    with pytest.raises(store.Conflict):
        store.add_plan(con, "demo-start", "Пример: Старт", 1900, "EUR", "month", key="plan-0002")


def test_plan_line_and_currency(con):
    store.add_plan(con, "demo-pro", "Пример: Про", 2500, "EUR", "month", key="plan-0001")
    inv = draft(con, lines=[{"plan": "demo-pro", "qty": 2}])
    assert inv["total"] == 5000 and inv["items"][0]["plan"] == "demo-pro"
    with pytest.raises(ValueError):
        store.create(con, "К", "USD", [{"plan": "demo-pro"}], key="usd-0001")   # валюта тарифа ≠ валюты счёта


# ---------- переходы статуса ----------

def test_status_only_allowed_transitions(con):
    inv = draft(con)
    with pytest.raises(ValueError):
        store.mark_paid(con, inv["id"], key="pay-0001", reason="рано")         # черновик не оплачивают
    with pytest.raises(ValueError):
        store.mark_paid(con, inv["id"], key="pay-0002", reason=" ")            # без основания — нельзя
    assert store.issue(con, inv["id"], key="iss-0001")["status"] == "issued"
    with pytest.raises(ValueError):
        store.issue(con, inv["id"], key="iss-0002")                            # дважды не выставить
    store.void(con, inv["id"], key="void-0001", reason="отменили")
    for fn in (lambda: store.issue(con, inv["id"], key="iss-0003"),
               lambda: store.mark_paid(con, inv["id"], key="pay-0003", reason="x"),
               lambda: store.void(con, inv["id"], key="void-0002", reason="x")):
        with pytest.raises(ValueError):
            fn()
    with pytest.raises(sqlite3.DatabaseError):                                  # и сама база держит переходы
        con.execute("UPDATE invoices SET status = 'draft' WHERE id = ?", (inv["id"],))
    d2 = draft(con, key="new-0002")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (d2["id"],))
    assert store.void(con, d2["id"], key="void-0003", reason="черновик не нужен")["status"] == "void"


def test_file_0600_and_wal(tmp_path):
    c = store.connect(tmp_path)
    draft(c)
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    c.close()
    assert (tmp_path / store.FILE).stat().st_mode & 0o777 == 0o600


# ---------- вебхук ----------

SECRET = b"s" * 32


def test_webhook_signature_time_replay(con):
    body = json.dumps({"id": "evt_1", "type": "payment.succeeded", "amount": 999}).encode()
    now = 1_800_000_000
    hdr = provider.sign(SECRET, body, now)
    seen = set()

    def once(sig):
        if sig in seen:
            return False
        seen.add(sig)
        return True

    assert provider.verify_signature([SECRET], body, hdr, now=now + 10, seen=once) == now
    with pytest.raises(provider.Replayed):                                       # тот же вебхук второй раз
        provider.verify_signature([SECRET], body, hdr, now=now + 11, seen=once)
    with pytest.raises(provider.BadSignature):                                   # подменили тело
        provider.verify_signature([SECRET], body.replace(b"999", b"1"), hdr, now=now, seen=once)
    with pytest.raises(provider.BadSignature):                                   # чужой секрет
        provider.verify_signature([SECRET], body, provider.sign(b"x" * 32, body, now), now=now, seen=once)
    with pytest.raises(provider.BadSignature):                                   # подменили время в заголовке
        provider.verify_signature([SECRET], body, hdr.replace(f"t={now}", f"t={now + 1}"), now=now, seen=once)
    for bad in ("", "v1=abc", f"t={now}", "t=x,v1=00"):
        with pytest.raises(provider.BadSignature):
            provider.verify_signature([SECRET], body, bad, now=now, seen=once)
    old = provider.sign(SECRET, body, now - provider.TOLERANCE - 1)
    with pytest.raises(provider.Expired):
        provider.verify_signature([SECRET], body, old, now=now, seen=once)
    future = provider.sign(SECRET, body, now + provider.TOLERANCE + 1)
    with pytest.raises(provider.Expired):
        provider.verify_signature([SECRET], body, future, now=now, seen=once)
    with pytest.raises(provider.Replayed):                                       # без защиты от повтора — отказ
        provider.verify_signature([SECRET], body, provider.sign(SECRET, body, now), now=now)
    rot = provider.sign(b"n" * 32, body, now) + ",v1=" + hdr.split("v1=")[1]     # смена секрета: два v1
    assert provider.verify_signature([b"n" * 32], body, rot, now=now, seen=once) == now
    # хранилище помнит подписи: повтор ловится и после перезапуска
    p = provider.JsonHmacProvider([SECRET])
    t = int(time.time())
    h2 = {"x-signature": provider.sign(SECRET, body, t)}
    ev = p.verify_webhook(h2, body, seen=lambda s: store.remember_webhook(con, s))
    assert ev.id == "evt_1" and ev.amount == 999
    with pytest.raises(provider.Replayed):
        p.verify_webhook(h2, body, seen=lambda s: store.remember_webhook(con, s))
    with pytest.raises(provider.BadSignature):
        provider.verify_signature([b"short"], body, hdr, now=now, seen=once)    # слабый секрет не принимаем


def test_none_provider_is_honest():
    p = provider.get("none")
    assert p.status() == {"name": "none", "connected": False, "note": provider.WAITING}
    with pytest.raises(provider.NotConnected, match="ждёт юрлица"):
        p.create_payment({"id": 1}, KEY)
    with pytest.raises(provider.NotConnected):
        p.verify_webhook({"x-signature": provider.sign(SECRET, b"{}", int(time.time()))}, b"{}")


# ---------- API: права и путь целиком ----------

def test_api_owner_only_and_flow(server, monkeypatch):  # noqa: F811
    panel, base = server
    owner, member, viewer = (panel.auth.issue(u) for u in (1, 2, 3))
    body = {"key": "api-new-01", "client": "Клиент «Пример»", "currency": "EUR",
            "lines": [{"title": "Пример услуги", "qty": 2, "price": "12.50"}]}
    for tok in (member, viewer):
        for p in ("/api/billing/plans", "/api/billing/invoices", "/api/billing/invoice?id=1"):
            assert call(base, p, None, tok)[0] == 403, p
        assert call(base, "/api/billing/invoice/new", body, tok)[0] == 403
    assert call(base, "/api/billing/plans")[0] == 401
    st, d, _ = call(base, "/api/billing/plans", None, owner)
    assert st == 200 and d["plans"] == [] and d["provider"]["connected"] is False
    st, d, _ = call(base, "/api/billing/invoice/new", body, owner)
    assert st == 403 and d["code"] == "confirm"                                   # новый вход браузера — сначала код
    monkeypatch.setattr(panel.auth, "needs_confirm", lambda *a, **k: False)
    st, inv, _ = call(base, "/api/billing/invoice/new", body, owner)
    assert st == 200 and inv["total"] == 2500 and inv["total_text"] == "25.00 EUR" and inv["status"] == "draft"
    assert call(base, "/api/billing/invoice/new", body, owner)[1]["id"] == inv["id"]    # повтор запроса
    bad = {**body, "key": "api-new-02", "lines": [{"title": "x", "price": "1.005"}]}
    assert call(base, "/api/billing/invoice/new", bad, owner)[0] == 400
    assert call(base, "/api/billing/invoice/pay", {"id": inv["id"], "key": "api-pay-01", "reason": "x"},
                owner)[0] == 400                                                  # черновик — сначала выставить
    st, d, _ = call(base, "/api/billing/invoice/issue", {"id": inv["id"], "key": "api-iss-01"}, owner)
    assert st == 200 and d["status"] == "issued" and d["balance"] == 2500
    assert call(base, "/api/billing/invoice/pay", {"id": inv["id"], "key": "api-pay-02"}, owner)[0] == 400
    st, d, _ = call(base, "/api/billing/invoice/pay", {"id": inv["id"], "key": "api-pay-03",
                                                      "reason": "выписка банка"}, owner)
    assert st == 200 and d["status"] == "paid" and d["balance"] == 0
    st, d, _ = call(base, "/api/billing/invoice/void", {"id": inv["id"], "key": "api-void-1", "reason": "ошибка"},
                    owner)
    assert st == 200 and d["status"] == "void" and [x["op"] for x in d["journal"]].count("reversal") == 2
    st, d, _ = call(base, "/api/billing/invoices", None, owner)
    assert st == 200 and d["invoices"][0]["number"].startswith("GP-")
    assert call(base, "/api/billing/invoice?id=999", None, owner)[0] == 404
    f = panel.cfg.data / store.FILE
    assert f.exists() and f.stat().st_mode & 0o777 == 0o600
