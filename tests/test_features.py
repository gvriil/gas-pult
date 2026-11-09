"""Учёт функций панели и месячный отчёт (features.py): только id, не чаще раза в минуту на функцию; 1-го числа —
владельцам и файлом usage-ГГГГ-ММ.md; «gas-pult usage report» — сейчас. Время подменяется."""

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import bot, cli, features, webapp, webauth
from gas_pult.config import Config

T0 = datetime(2026, 11, 9, 12, 0).timestamp()
DAY = 86400


@pytest.fixture
def uses(tmp_path):
    return features.Uses(tmp_path / "features.json")


def test_record_only_ids_and_once_a_minute(uses, tmp_path):
    assert uses.record(["home.projects", "sheet.focus", "act:say"], T0) == 3
    assert uses.record(["home.projects"], T0 + 30) == 0                     # та же минута — не пишем
    assert uses.record(["home.projects"], T0 + 61) == 1
    assert uses.record(["Привет, это текст", "../etc", "x" * 80, "", None, 5], T0 + 200) == 0   # не id — мимо
    raw = (tmp_path / "features.json").read_text()
    assert (tmp_path / "features.json").stat().st_mode & 0o777 == 0o600
    assert set(json.loads(raw)) == {"home.projects", "sheet.focus", "act:say"}
    st = uses.stats(T0 + 300)
    assert st["home.projects"] == {"last": int(T0 + 61), "month": 2} and st["act:say"]["month"] == 1


def test_record_caps_batch(uses):
    assert uses.record([f"x.{i}" for i in range(50)], T0) == features.MAX_IDS


def test_old_days_drop_out(uses):
    uses.record(["sheet.focus"], T0 - 45 * DAY)
    uses.record(["home.projects"], T0 - 35 * DAY)
    uses.record(["home.projects"], T0 - 2 * DAY)
    st = uses.stats(T0)
    assert st["home.projects"]["month"] == 1 and st["sheet.focus"]["month"] == 0
    raw = json.loads(uses.store.read_text())
    assert all(d >= "2026-09-30" for d in raw["home.projects"]["days"])     # счётчики старше 40 дней — удалены


def test_report_unused_and_top(uses, monkeypatch):
    monkeypatch.setattr(features, "catalog", lambda: {"home.projects": "Проекты", "sheet.focus": "Фокус-ссылка",
                                                      "settings.people": "Люди", "home.commands": "Команды"})
    uses.record(["sheet.focus"], T0 - 40 * DAY)                               # открывали, но больше месяца назад
    uses.record(["act:say"], T0 - 5 * DAY)
    uses.record(["home.projects"], T0 - 3 * DAY)
    uses.record(["home.projects"], T0 - DAY)
    uses.record(["home.projects"], T0 - DAY + 120)
    r = features.report(uses, T0)
    assert r["month"] == "2026-11"
    assert [k for k, _, _ in r["unused"]] == ["home.commands", "settings.people", "sheet.focus"]   # «ни разу» — первыми
    assert r["unused"][2][2] == int(T0 - 40 * DAY)
    assert r["top"] == [("home.projects", "Проекты", 3), ("act:say", "act:say", 1)]
    md = features.markdown(r)
    assert "не открывали 30 дней: 3" in md.lower() and "`sheet.focus` — Фокус-ссылка (последний раз: 30.09.2026)" in md
    assert "1. `home.projects` — Проекты: 3" in md
    tg = features.telegram(r, Path("/x/usage-2026-11.md"))
    assert "не открывали 30 дней — 3 из 4" in tg and "• Люди" in tg and "Проекты — 3" in tg and "usage-2026-11.md" in tg


def test_catalog_is_panel_screens():
    cat = features.catalog()
    assert "home.projects" in cat and "sheet.focus" in cat and len(cat) > 40
    assert not any(k.startswith("offer") for k in cat)


def test_due_first_of_month_once(tmp_path):
    first = datetime(2026, 12, 1, 9, 0)
    assert not features.due(tmp_path, datetime(2026, 11, 30, 9, 0))
    assert features.due(tmp_path, first)
    features.mark_sent(tmp_path, first)
    assert not features.due(tmp_path, datetime(2026, 12, 1, 10, 0))          # в тот же день — один раз
    assert features.due(tmp_path, datetime(2027, 1, 1, 0, 5))
    assert features.previous(first) == "2026-11" and features.previous(datetime(2027, 1, 1)) == "2026-12"


def test_bot_sends_monthly_report(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    b = bot.Pult(Config(token="1:T", owners=[1]))
    features.Uses(b.cfg.data / "features.json").record(["home.projects"], datetime(2026, 11, 20).timestamp())
    sent = []
    monkeypatch.setattr(b, "broadcast", lambda text, **kw: sent.append(text))
    b.send_features(datetime(2026, 12, 1, 9, 0))
    assert len(sent) == 1 and sent[0].startswith("📊 Функции панели за 2026-11")
    f = b.cfg.data / "usage-2026-11.md"
    assert f.is_file() and "home.projects" in f.read_text() and f.stat().st_mode & 0o777 == 0o600


def test_cli_usage_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    features.Uses(tmp_path / "features.json").record(["sheet.focus"])
    cli.main(["usage", "report"])
    out = capsys.readouterr().out
    month = datetime.now().strftime("%Y-%m")
    assert f"отчёт за {month}" in out and (tmp_path / f"usage-{month}.md").is_file()


def test_api_uses_records_for_any_role(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "data").mkdir()
    p = webapp.Panel(Config(token="1:T", owners=[1], region="NL"))
    p.people.add(5, "viewer", "Наблюдатель")
    for uid in (1, 5):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(body, uid):
        req = urllib.request.Request(base + "/api/uses", json.dumps(body).encode(),
                                     {"Cookie": f"{webauth.COOKIE}={p.auth.issue(uid)}"} if uid else {})
        try:
            r = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            r = e
        return (r.status if hasattr(r, "status") else r.code), json.loads(r.read() or b"{}")

    try:
        assert call({"ids": ["home.projects", "act:say"]}, 1) == (200, {"n": 2})
        assert call({"ids": ["sheet.focus", "home.projects"]}, 5) == (200, {"n": 1})   # наблюдателю — тоже
        assert call({"ids": "home.projects"}, 1) == (200, {"n": 0})
        assert call({"ids": ["x.y"]}, None)[0] == 401
        raw = (tmp_path / "data" / "features.json").read_text()
        assert "5" not in json.dumps(sorted(json.loads(raw)))                 # без людей
    finally:
        srv.shutdown()


def test_panel_marks_screens_and_actions():
    page = (Path(webapp.__file__).parent / "web" / "index.html").read_text(encoding="utf-8")
    assert 'api("/api/uses", { ids })' in page and 'useMark("act:" + b.dataset.act)' in page
    assert "if (id && !DEMO && meta) USE.ids.add(id)" in page
