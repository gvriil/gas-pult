"""«Изменена N назад» (ago.py): шкала на границах, формы числа ru/en, точное время, давние сессии, времена из
журнала и экрана, поля API панели, строки бота; та же шкала в index.html (константы — статически, тексты — в браузере,
если есть Playwright). Живой tmux и настоящий Claude не нужны."""

import importlib.util
import json
import re
import shutil
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import activity, ago, bot, transcripts, webapp
from gas_pult.config import Config

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "gas_pult" / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
NOW = 1793779200.0                    # 2026-11-04 08:00:00 UTC
MIN, H, D = 60, 3600, 86400


@pytest.fixture
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


# ---------- формы числа ----------
@pytest.mark.parametrize("n, form", [(0, "many"), (1, "one"), (2, "few"), (3, "few"), (4, "few"), (5, "many"),
                                     (11, "many"), (12, "many"), (14, "many"), (20, "many"), (21, "one"),
                                     (22, "few"), (25, "many"), (101, "one"), (111, "many"), (112, "many"),
                                     (122, "few")])
def test_plural_ru(n, form):
    assert ago.plural(n, "ru") == form


def test_plural_en():
    assert [ago.plural(n, "en") for n in (0, 1, 2, 5, 21)] == ["many", "one", "many", "many", "many"]


# ---------- шкала на границах ----------
@pytest.mark.parametrize("sec, ru, en", [
    (0, "только что", "just now"), (4, "только что", "just now"), (-30, "только что", "just now"),
    (5, "5 с назад", "5 s ago"), (59, "59 с назад", "59 s ago"),
    (60, "1 мин", "1 min"), (119, "1 мин", "1 min"), (3599, "59 мин", "59 min"),
    (H, "1 ч", "1 h"), (D - 1, "23 ч", "23 h"),
    (D, "вчера", "yesterday"), (2 * D - 1, "вчера", "yesterday"),
    (2 * D, "2 дн", "2 d"), (7 * D - 1, "6 дн", "6 d"),
    (7 * D, "1 нед", "1 wk"), (30 * D - 1, "4 нед", "4 wk"),
    (30 * D, "1 мес", "1 mo"), (365 * D - 1, "12 мес", "12 mo"),
])
def test_short_scale_boundaries(sec, ru, en):
    assert ago.ago(NOW - sec, NOW, "ru") == ru
    assert ago.ago(NOW - sec, NOW, "en") == en


@pytest.mark.parametrize("sec, ru, en", [
    (21, "21 секунду назад", "21 seconds ago"), (22, "22 секунды назад", "22 seconds ago"),
    (59, "59 секунд назад", "59 seconds ago"),
    (60, "1 минуту назад", "1 minute ago"), (120, "2 минуты назад", "2 minutes ago"),
    (300, "5 минут назад", "5 minutes ago"), (11 * MIN, "11 минут назад", "11 minutes ago"),
    (21 * MIN, "21 минуту назад", "21 minutes ago"), (24 * MIN, "24 минуты назад", "24 minutes ago"),
    (H, "1 час назад", "1 hour ago"), (3 * H, "3 часа назад", "3 hours ago"), (5 * H, "5 часов назад", "5 hours ago"),
    (21 * H, "21 час назад", "21 hours ago"),
    (D, "вчера", "yesterday"), (2 * D, "2 дня назад", "2 days ago"), (5 * D, "5 дней назад", "5 days ago"),
    (7 * D, "1 неделю назад", "1 week ago"), (14 * D, "2 недели назад", "2 weeks ago"),
    (30 * D, "1 месяц назад", "1 month ago"), (90 * D, "3 месяца назад", "3 months ago"),
    (150 * D, "5 месяцев назад", "5 months ago"), (330 * D, "11 месяцев назад", "11 months ago"),
])
def test_full_forms(sec, ru, en):
    assert ago.ago(NOW - sec, NOW, "ru", full=True) == ru
    assert ago.ago(NOW - sec, NOW, "en", full=True) == en


def test_date_and_exact(utc):
    ts = NOW - 400 * D                                              # больше года — дата
    assert ago.ago(ts, NOW, "ru") == "30.09.2025" and ago.ago(ts, NOW, "en") == "2025-09-30"
    assert ago.ago(ts, NOW, "ru", full=True) == "30.09.2025"
    t = 1793796672.0                                                # 2026-11-04 12:51:12 UTC
    assert ago.exact(t, NOW, "ru") == "04.11, 12:51:12" and ago.exact(t, NOW, "en") == "11/04, 12:51:12"
    assert ago.exact(ts, NOW, "ru") == "30.09.2025, 08:00:00"       # другой год — с годом
    assert ago.exact(ts, NOW, "en") == "09/30/2025, 08:00:00"
    assert ago.ago(None, NOW) == "" and ago.exact(0, NOW) == ""


def test_exact_follows_local_timezone(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Moscow")
    time.tzset()
    try:
        assert ago.exact(1793796672.0, NOW, "ru") == "04.11, 15:51:12"
    finally:
        monkeypatch.undo()
        time.tzset()


def test_stale():
    assert not ago.stale(NOW - 7 * D, NOW) and ago.stale(NOW - 7 * D - 1, NOW)
    assert not ago.stale(None, NOW) and not ago.stale(0, NOW)


# ---------- откуда берётся время ----------
def entry(kind, t, content):
    return {"type": kind, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t)),
            "message": {"role": kind, "content": content, "stop_reason": "end_turn" if kind == "assistant" else None}}


def test_journal_said_and_asked():
    j = activity.parse([entry("user", NOW - 300, "сделай отчёт"),
                        entry("assistant", NOW - 200, [{"type": "text", "text": "готово"}]),
                        entry("user", NOW - 100, "спасибо")])
    assert (j["turn"], j["said"], j["last"]) == (NOW - 100, NOW - 200, NOW - 100)
    st = ago.stamps(j)
    assert st == {"changed": NOW - 100, "said": NOW - 200, "asked": NOW - 100}
    assert ago.stamps(j, screen_at=NOW - 5)["changed"] == NOW - 5           # экран новее журнала
    assert ago.stamps({}) == {"changed": None, "said": None, "asked": None}
    assert ago.stamps({}, mtime=NOW - 9)["changed"] == NOW - 9               # в хвосте нет времени — файл


def test_tool_use_is_not_an_answer():
    j = activity.parse([entry("user", NOW - 300, "x"),
                        entry("assistant", NOW - 250, [{"type": "tool_use", "id": "a", "name": "Read", "input": {}}])])
    assert j["said"] == 0.0 and j["last"] == NOW - 250


def test_screen_changes():
    clock = [NOW]
    s = ago.Screens(clock=lambda: clock[0])
    box = ["─" * 40, "❯ ", "─" * 40]
    assert s.look("@1", ["ответ", *box, "статус 10:00:01"]) == 0.0            # первый взгляд — неизвестно
    clock[0] += 10
    assert s.look("@1", ["ответ", *box, "статус 10:00:11"]) == 0.0            # строка статуса под полем — не в счёт
    assert s.look("@1", ["ответ", "─" * 40, "❯ печатаю", "─" * 40]) == 0.0      # поле ввода — тоже
    clock[0] += 5
    assert s.look("@1", ["ответ", "✻ Pondering… (1s)", *box]) == NOW + 15      # экран над полем сменился
    assert s.at("@1") == NOW + 15 and s.at("@9") == 0.0


def test_bot_line():
    st = {"changed": NOW - 300, "said": NOW - 420, "asked": NOW - 300}
    line = ago.line(st, NOW)
    assert line.startswith("изменена 5 минут назад (") and "ответ агента — 7 минут назад" in line
    assert "ваше сообщение" not in line                                     # совпадает с изменением
    assert ago.line({"changed": None}, NOW) == ""
    assert ago.line(st, NOW, "en").startswith("changed 5 minutes ago (")


# ---------- API панели и бот ----------
@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", tmp_path / "projects")
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    d = transcripts.project_dir("/w/proj")
    d.mkdir(parents=True)
    now = time.time()
    (d / "s.jsonl").write_text("".join(json.dumps(e) + "\n" for e in (
        entry("user", now - 3 * H, "x"), entry("assistant", now - 2 * H, [{"type": "text", "text": "ok"}]))))
    wins = [{"id": "@1", "idx": "1", "path": "/w/proj", "cmd": "claude", "by": "", "name": "proj", "mark": "claude",
             "channel": False, "profile": "claude"},
            {"id": "@2", "idx": "2", "path": "/w/none", "cmd": "claude", "by": "", "name": "none", "mark": "claude",
             "channel": False, "profile": "claude"}]
    screen = {"@1": ["старый ответ", "─" * 30, "❯ ", "─" * 30], "@2": ["пусто"]}
    monkeypatch.setattr(p.tmux, "windows", lambda: wins)
    monkeypatch.setattr(p.tmux, "screen", lambda wid, n=25: screen[wid])
    return p, screen, now


def test_sessions_api_fields(panel):
    p, screen, now = panel
    s = {x["id"]: x for x in p.sessions()}
    assert abs(s["@1"]["changed"] - (now - 2 * H)) < 2 and abs(s["@1"]["asked"] - (now - 3 * H)) < 2
    assert s["@1"]["said"] == s["@1"]["changed"]
    assert s["@2"]["changed"] is None and s["@2"]["said"] is None              # журнала нет — неизвестно
    screen["@1"] = ["новый ответ", "─" * 30, "❯ ", "─" * 30]                  # экран сменился — изменена сейчас
    s = {x["id"]: x for x in p.sessions()}
    assert time.time() - s["@1"]["changed"] < 5 and abs(s["@1"]["said"] - (now - 2 * H)) < 2


def test_bot_windows_and_status(panel, monkeypatch):
    p = panel[0]
    pult, sent = p.pult, []
    monkeypatch.setattr(pult, "send", lambda chat, text, **kw: sent.append((text, kw)) or {})
    pult.show_windows(1)
    labels = [r[0]["text"] for r in sent[-1][1]["reply_markup"]["inline_keyboard"]]
    assert labels[0].startswith("1: proj") and "2 ч" in labels[0]       # с временем — выше, без — ниже
    assert labels[1].startswith("2: none") and labels[1].count(" · ") == 1           # имя · папка, без времени
    monkeypatch.setattr(pult, "run_slash", lambda wid, cmd: ["Status", "Version 2"])
    pult.slash(1, p.tmux.windows()[0], "/status")
    assert "🕓 изменена 2 часа назад (" in sent[-1][0]
    pult.slash(1, p.tmux.windows()[0], "/context")
    assert "🕓" not in sent[-1][0]


def test_bot_windows_waiting_first(panel, monkeypatch):
    p, screen, _ = panel
    pult, sent = p.pult, []
    screen["@2"] = ["Do you want to proceed?", "❯ 1. Yes", "Esc to cancel"]
    monkeypatch.setattr(pult, "send", lambda chat, text, **kw: sent.append((text, kw)) or {})
    pult.show_windows(1)
    labels = [r[0]["text"] for r in sent[-1][1]["reply_markup"]["inline_keyboard"]]
    assert labels[0].startswith("2: ⏸ none")
    assert bot.DIALOG.search("\n".join(screen["@2"]))


# ---------- та же шкала в панели ----------
def test_js_constants_match_python():
    steps = json.loads(re.search(r"^const AGO_STEPS = (\[.*\]);$", INDEX, re.M).group(1))
    assert [tuple(x) for x in steps] == list(ago.STEPS)
    assert json.loads(re.search(r"^const AGO_UNIT = (\{.*\});$", INDEX, re.M).group(1)) == ago.UNIT
    assert int(re.search(r"^const AGO_STALE = (\d+);$", INDEX, re.M).group(1)) == ago.STALE


def test_dictionary_keys_for_every_step():
    ru = json.loads((WEB / "i18n" / "ru.json").read_text(encoding="utf-8"))
    en = json.loads((WEB / "i18n" / "en.json").read_text(encoding="utf-8"))
    for d in (ru, en):
        for u in ago.UNIT:
            assert {f"ago.{u}", f"ago.{u}.one", f"ago.{u}.few", f"ago.{u}.many"} <= d.keys()
        assert {"ago.now", "ago.yesterday", "ago.date", "ago.exact", "ago.exact.year"} <= d.keys()


def test_js_same_as_python_in_browser(monkeypatch):
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    monkeypatch.setenv("TZ", "Europe/Moscow")
    time.tzset()
    spec = importlib.util.spec_from_file_location("ago_check", ROOT / "tests" / "e2e" / "ago_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
        monkeypatch.undo()
        time.tzset()
