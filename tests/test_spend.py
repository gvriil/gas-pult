"""Расход по ценам API (владелец 22.11): разбор записей очереди оповещений и свод за сегодня / вчера / 7 дней;
``GET /api/spend`` — только владельцу."""

import json
from datetime import datetime

import pytest
from test_project_chats import call
from test_project_chats import server as server

from gas_pult import spend


def ts(*a):
    return datetime(*a).timestamp()                   # местное время — как у сервера: от часового пояса не зависит


def rec(at, hours, total, **projects):
    body = "".join(f"\n  {k.replace('_', '-')}: ${v:.2f}" for k, v in projects.items())
    return {"ts": at, "text": f"💰 По ценам API за {hours}: ${total:.2f}{body}\n  с начала суток: $0.00"}


@pytest.fixture
def queue(tmp_path, monkeypatch):
    f = tmp_path / "queue.jsonl"
    monkeypatch.setenv(spend.ENV, str(f))
    spend._cache.clear()

    def write(*rows, raw=()):
        f.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows) + "".join(x + "\n" for x in raw),
                     encoding="utf-8")
    return write


def test_parse_example_and_midnight():
    r = spend.parse(ts(2026, 11, 22, 0, 1), "💰 По ценам API за 23:00–00:00: $15.15\n  shtab: $6.78\n"
                    "  gas-pult: $3.70\n  с начала суток: $0.00")
    assert r["day"].isoformat() == "2026-11-21" and r["hour"] == 23        # час 23:00–00:00 — прошлые сутки
    assert r["total"] == 15.15 and r["projects"] == {"shtab": 6.78, "gas-pult": 3.70}   # «с начала суток» — не проект
    r = spend.parse(ts(2026, 11, 22, 14, 0, 30), "💰 По ценам API за 13:00–14:00: $2.00\n  shtab: $2.00")
    assert r["day"].isoformat() == "2026-11-22" and r["hour"] == 13


@pytest.mark.parametrize("ts_, text", [
    (1795302061, "📣 Другое оповещение"), (1795302061, "💰 По ценам API за 25:00–26:00: $1.00"),
    ("вчера", "💰 По ценам API за 10:00–11:00: $1.00"), (1795302061, None), (1795302061, ""),
])
def test_parse_skips_foreign_and_broken(ts_, text):
    assert spend.parse(ts_, text) is None


def test_summary_today_yesterday_7d(queue):
    queue(rec(ts(2026, 11, 22, 0, 1), "23:00–00:00", 15.15, shtab=6.78, gas_pult=3.70),       # 21.11, 23 ч
          rec(ts(2026, 11, 22, 10, 0), "09:00–10:00", 4.00, shtab=1.00, gas_pult=3.00),
          rec(ts(2026, 11, 22, 11, 0), "10:00–11:00", 2.50, shtab=2.50),
          rec(ts(2026, 11, 22, 11, 2), "10:00–11:00", 3.00, shtab=3.00),                     # повтор часа — последний
          rec(ts(2026, 11, 16, 12, 0), "11:00–12:00", 1.00, old=1.00),                       # 7 дней: 16–22.11
          rec(ts(2026, 11, 15, 12, 0), "11:00–12:00", 9.00, older=9.00),                     # вне 7 дней
          raw=["не json", '{"ts": 1, "text": 5}', "[1, 2]", ""])
    now = datetime(2026, 11, 22, 12, 30)
    t = spend.summary("today", now)
    assert t["total"] == 7.0 and t["projects"] == [{"name": "shtab", "usd": 4.0}, {"name": "gas-pult", "usd": 3.0}]
    assert len(t["hours"]) == 24 and t["hours"][9]["usd"] == 4.0 and t["hours"][10]["usd"] == 3.0 and "days" not in t
    y = spend.summary("yesterday", now)
    assert y["total"] == 15.15 and y["hours"][23]["usd"] == 15.15
    assert y["projects"][0] == {"name": "shtab", "usd": 6.78} and {"name": "прочее", "usd": 4.67} in y["projects"]
    w = spend.summary("7d", now)
    assert w["total"] == 23.15 and w["days"][0]["date"] == "2026-11-16" and len(w["days"]) == 7
    assert w["days"][-1]["usd"] == 7.0 and "older" not in {p["name"] for p in w["projects"]}
    assert w["updated"] == ts(2026, 11, 22, 11, 2)
    with pytest.raises(ValueError):
        spend.summary("month", now)


def test_no_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv(spend.ENV, str(tmp_path / "нет.jsonl"))
    s = spend.summary("today")
    assert s["total"] == 0 and s["projects"] == [] and s["updated"] is None


def test_api_owner_only(server, queue):
    p, base, *_ = server
    queue(rec(datetime.now().timestamp(), f"{datetime.now().hour:02d}:00–00:00", 1.25, shtab=1.25))
    code, body = call(base, "/api/spend?period=today", tok=p.auth.issue(1))
    assert code == 200 and set(body) >= {"total", "projects", "hours", "updated"}
    assert call(base, "/api/spend?period=7d", tok=p.auth.issue(1))[1]["days"]
    assert call(base, "/api/spend", tok=p.auth.issue(2))[0] == 403            # не владельцу — нет
