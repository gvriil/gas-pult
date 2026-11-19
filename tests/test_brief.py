"""Утренний брифинг первого лица (GAS-18): строки с источником, блоки, письма без ответа, Linear, тишина, бот."""

import json
import time
from datetime import datetime
from types import SimpleNamespace

import pytest

from gas_pult import bot, brief, digest, notifylevel
from gas_pult.connectors import _core, mail_mcp

NOW = datetime(2026, 11, 18, 7, 30)
ME = "owner@example.org"


def test_row_without_source_is_dropped():
    assert brief.row("текст", None) is None
    assert brief.row("текст", {"kind": "mail"}) is None                      # без подписи — тоже нет источника
    r = brief.row("текст", {"kind": "mail", "label": "Gmail", "url": ""})
    assert r == {"text": "текст", "source": {"kind": "mail", "label": "Gmail"}}
    b = brief.assemble(now=NOW, done=[None, r], decisions=[None])
    assert b["done"] == [r] and b["decisions"] == []


def test_headline_plural_and_night():
    assert brief.headline(1, 0) == "Ждут вас 1 решение. Ночью срочного не было."
    assert brief.headline(3, 0).startswith("Ждут вас 3 решения.")
    assert brief.headline(5, 2) == "Ждут вас 5 решений. Ночью — 2 срочных, уже присылал."
    assert brief.headline(0, 1).startswith("Решений от вас не ждут.")


def test_urgent_categories():
    assert brief.urgent("Счёт на оплату №12") == "money"
    assert brief.urgent("В ваш аккаунт выполнен вход") == "security"
    assert brief.urgent("Последний день подачи") == "deadline"
    assert brief.urgent("Привет, как дела?") is None
    assert notifylevel.wakes("money") and not notifylevel.wakes(None)


def msg(uid, frm, subject, to=ME, **kw):
    return {"uid": str(uid), "from": frm, "to": to, "cc": "", "subject": subject, "date": "2026-11-17T10:00:00+00:00",
            "message_id": f"<m{uid}@x>", "answered": False, **kw}


def test_unanswered_filters():
    inbox = [msg(1, "Анна <anna@example.org>", "Договор"),
             msg(2, f"Я <{ME}>", "Себе"),                                    # от себя
             msg(3, "Рассылка <team@example.org>", "Новости", to="all@example.org"),   # не владельцу
             msg(4, "Пётр <petr@example.org>", "Смета", answered=True),      # флаг «отвечено»
             msg(5, "Олег <oleg@example.org>", "Встреча"),                   # ответ в «Отправленных»
             msg(6, "GitHub <notifications@github.com>", "PR merged")]
    sent = [{"subject": "Re: Встреча"}]
    got = brief.unanswered(inbox, sent, ME)
    assert [(m["uid"], m["auto"]) for m in got] == [("1", False), ("6", True)]


@pytest.fixture
def box(monkeypatch):
    cfg = {"imap_host": "imap.gmail.com", "user": ME}
    monkeypatch.setattr(mail_mcp, "_box", lambda b: (b, cfg))
    sent = {"folders": [{"name": "[Gmail]/Sent", "role": "отправленные"}]}
    monkeypatch.setattr(mail_mcp, "list_folders", lambda a: sent)
    inbox = [msg(1, "Анна <anna@example.org>", "Договор"),
             msg(2, "Сервис <no-reply@example.com>", "Еженедельные новости"),      # рассылка — не решение
             msg(3, "Банк <alerts@bank.example>", "Новый вход в аккаунт")]          # рассылка, но срочно
    monkeypatch.setattr(mail_mcp, "list_messages", lambda a: {"rows": inbox if a.get("folder") is None else []})
    return cfg


def test_mail_items_reply_and_check(box):
    items, status = brief.mail_items(["gmail"], "2026-11-17")
    assert status == [{"id": "mail:gmail", "label": "Gmail · gmail", "state": "ok"}]
    rows = [brief.decision(x) for x in items]
    assert [r["text"] for r in rows] == ["Ответить Анна: «Договор»",
                                         "[безопасность] Проверить: «Новый вход в аккаунт» — Банк"]
    assert rows[0]["source"]["url"].startswith("https://mail.google.com/mail/?authuser=")
    assert "rfc822msgid%3Am1%40x" in rows[0]["source"]["url"] and rows[0]["yes"] == "откроет письмо в Gmail"
    assert rows[1]["cat"] == "security"


def test_mail_box_error_is_status_not_crash(monkeypatch):
    def boom(b):
        raise _core.ToolError("сервер недоступен")
    monkeypatch.setattr(mail_mcp, "_box", boom)
    items, status = brief.mail_items(["gmail"], "2026-11-17")
    assert items == [] and status[0]["state"] == "error" and "недоступен" in status[0]["note"]


def test_linear_done_and_late(monkeypatch, tmp_path):
    monkeypatch.setattr(_core, "SECRETS_DIR", tmp_path)
    (tmp_path / "linear.token").write_text("lin_x\n")
    seen = {}

    def http(method, url, **kw):
        seen.update(kw)
        done = [{"identifier": "GAS-1", "title": "Сделано", "url": "u1"}]
        late = [{"identifier": "GAS-2", "title": "Горит", "url": "u2", "dueDate": "2026-11-17",
                 "state": {"name": "In Progress"}}]
        return {"data": {"done": {"assignedIssues": {"nodes": done}}, "late": {"assignedIssues": {"nodes": late}}}}
    done, late = brief.linear("2026-11-17", "2026-11-18", http=http)
    assert seen["headers"] == {"Authorization": "lin_x"} and seen["keys"] == ["lin_x"]
    assert '"2026-11-17T00:00:00Z"' in seen["body"]["query"] and '{lt: "2026-11-18"}' in seen["body"]["query"]
    assert done[0]["source"] == {"kind": "linear", "label": "Linear · GAS-1", "url": "u1"}
    assert late[0]["why"].startswith("срок 2026-11-17 прошёл") and late[0]["cat"] == "deadline"


def test_pult_tasks_done_and_overdue():
    items = [{"title": "Готово", "status": "done", "done_at": NOW.timestamp() - 3600},
             {"title": "Давно", "status": "done", "done_at": NOW.timestamp() - 5 * 86400},
             {"title": "Горит", "status": "doing", "due": "2026-11-10", "next": "позвонить"}]
    done, late = brief.pult_tasks(items, NOW.timestamp() - 86400, "2026-11-18")
    assert [r["text"] for r in done] == ["Готово"]
    assert late[0]["why"] == "срок 2026-11-10 прошёл; дальше: позвонить"


def test_collect_blocks(monkeypatch, tmp_path):
    monkeypatch.setattr(brief, "merged", lambda owner, since: [brief.row("Слит PR me/r#1", {"kind": "github",
                                                                                          "label": "GitHub · me/r#1"})])
    pr_red = {"kind": "pr", "key": "p2", "repo": "me/r", "n": 2, "title": "Красный", "url": "https://x/2", "age": 0,
              "ci": "FAILURE", "ok": False}
    pr_ok = {"kind": "pr", "key": "p3", "repo": "me/r", "n": 3, "title": "Зелёный", "url": "https://x/3", "age": 3,
             "ci": "SUCCESS", "ok": True}
    yes = {"kind": "yes", "key": "h1", "project": "shop", "path": "/p/shop", "text": "Ждут «да»: витрина"}
    d = digest.Digest(tmp_path / "digest.json")
    d.snooze("h1", digest.LATER)                                            # отложенное — не показываем
    cfg = SimpleNamespace(digest_github="me")
    sel = {"sources": ["mail", "calendar", "github", "pult"], "boxes": [], "calendars": []}
    b = brief.collect(cfg, sel=sel, digest_items=[pr_red, pr_ok, yes], tasks_list=[], now=NOW,
                      fresh=lambda xs: d.fresh(xs, time.time()))
    assert [r["text"] for r in b["done"]] == ["Слит PR me/r#1"]
    assert b["failed"][0]["why"].startswith("CI красный")
    assert [r["key"] for r in b["decisions"]] == ["p3"] and b["decisions"][0]["act"] == "confirm"
    assert b["headline"] == "Ждут вас 1 решение. Ночью срочного не было."
    st = {s["id"]: s["state"] for s in b["sources"]}
    assert st == {"mail": "none", "calendar": "none", "github": "ok", "linear": "off", "pult": "ok"}
    assert d.item("p3") and not d.item("p2")                               # кнопки решений — через digest
    for block in ("done", "failed", "today", "decisions"):
        assert all(r["source"]["kind"] and r["source"]["label"] for r in b[block])


def test_prefs_and_default_choice(tmp_path):
    avail = {"boxes": [{"id": "gmail", "gmail": True}, {"id": "ya", "gmail": False}], "calendars": ["work"],
             "linear": False, "github": True}
    p = brief.Prefs(tmp_path / "brief_prefs.json")
    sel = brief.chosen(p.get(1), avail)
    assert sel == {"sources": ["mail", "calendar", "github", "pult"], "chosen": False, "boxes": ["gmail"],
                   "calendars": ["work"]}
    rec = p.set(1, ["calendar", "apple", "mail"], boxes=["ya"])
    assert rec["sources"] == ["mail", "calendar"]                           # Apple — «скоро», не подключается
    assert brief.chosen(p.get(1), avail)["boxes"] == ["ya"] and p.get(2) == {}
    assert (tmp_path / "brief_prefs.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        p.set(1, ["telepathy"])


def test_telegram_text_and_decision_buttons():
    b = brief.assemble(now=NOW, done=[brief.row("Сделано", {"kind": "linear", "label": "Linear · GAS-1", "url": "https://l/1"})],
                       failed=[brief.row("PR <b>", {"kind": "github", "label": "GitHub"}, why="CI красный")],
                       status=[{"id": "calendar", "label": "Календарь", "state": "none", "note": "нужна ссылка"}])
    t = brief.telegram(b)
    assert '<a href="https://l/1">Linear · GAS-1</a>' in t and "PR &lt;b&gt; — CI красный · GitHub" in t
    assert "Не подключено: Календарь — нужна ссылка" in t
    r = brief.row("Ответить Анна", {"kind": "mail", "label": "Gmail", "url": "https://m/1"}, key="k1", yes="откроет",
                  act="open")
    text, kbd = brief.decision_msg(2, r, "https://panel/?view=brief")
    assert text.startswith("2. Ответить Анна") and "«Да» — откроет." in text
    (yes, no, later), (panel,) = kbd["inline_keyboard"]
    assert yes == {"text": "✅ Да", "url": "https://m/1"} and no["callback_data"] == "dg:c:k1"
    assert later["callback_data"] == "dg:l:k1" and panel["web_app"]["url"].endswith("view=brief")
    r2 = {**r, "act": "confirm"}
    assert brief.decision_msg(1, r2)[1]["inline_keyboard"][0][0]["callback_data"] == "dg:y:k1"


def test_alerts_first_run_silent_then_once(tmp_path):
    a = brief.Alerts(tmp_path / "brief_alerts.json")
    t = datetime(2026, 11, 18, 2, 0).timestamp()
    assert a.new(["old"], t) == []                                           # первый запуск: старым не будим
    assert a.new(["old", "x"], t + 60) == ["x"]
    assert a.new(["x"], t + 120) == []                                       # второй раз — нет
    a.new(["shown"], t + 180, woke=False)                                    # показали в брифинге — не «ночью»
    assert a.night(datetime(2026, 11, 18, 7, 30)) == 1
    assert json.loads((tmp_path / "brief_alerts.json").read_text())["shown"][1] is False


# ---------- бот ----------
def make(tmp_path, monkeypatch, brief_at="07:30"):
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = SimpleNamespace(owners=[1], brief_at=brief_at, digest_at="09:00", data=tmp_path)
    p.digest = digest.Digest(tmp_path / "digest.json")
    p.alerts = brief.Alerts(tmp_path / "brief_alerts.json")
    p.brief_prefs = brief.Prefs(tmp_path / "brief_prefs.json")
    p.sent = []
    p.send = lambda chat, text, **kw: p.sent.append((chat, text, kw)) or {}
    p.broadcast = lambda text, **kw: p.sent.append((0, text, kw))
    p.panel_url = lambda view="": "https://panel/?view=" + view
    return p


def fake_brief(decisions):
    return brief.assemble(now=NOW, decisions=decisions)


def test_send_brief_text_then_decisions_one_by_one(tmp_path, monkeypatch):
    p = make(tmp_path, monkeypatch)
    d1 = brief.row("Ответить Анна", {"kind": "mail", "label": "Gmail"}, key="m1", cat="money")
    d2 = brief.row("PR me/r#3", {"kind": "github", "label": "GitHub"}, key="p3", act="confirm")
    p.brief_now = lambda now=None, uid=None: fake_brief([d1, d2])
    p.send_brief(5)
    assert [c for c, *_ in p.sent] == [5, 5, 5]
    assert p.sent[0][1].startswith("☀️ <b>Ждут вас 2 решения.") and p.sent[0][2]["parse_mode"] == "HTML"
    assert p.sent[1][1].startswith("1. Ответить Анна") and p.sent[2][1].startswith("2. PR me/r#3")
    assert "m1" in p.alerts.load()                                         # срочное показано — ночью не будить


def test_check_urgent_wakes_once_and_only_urgent(tmp_path, monkeypatch):
    p = make(tmp_path, monkeypatch)
    p.alerts.new([], 0)                                                    # не первый запуск
    hot = brief.row("Счёт на оплату", {"kind": "mail", "label": "Gmail"}, key="m1", cat="money")
    calm = brief.row("Ответить Анна", {"kind": "mail", "label": "Gmail"}, key="m2")
    p.brief_now = lambda now=None, uid=None: fake_brief([hot, calm])
    p.check_urgent(NOW)
    p.check_urgent(NOW)
    assert len(p.sent) == 1 and p.sent[0][1].startswith("🚨 Срочно: Счёт на оплату")


def test_morning_sends_brief_instead_of_digest(tmp_path, monkeypatch):
    p = make(tmp_path, monkeypatch)
    calls = []
    p.send_brief = lambda chat=None: calls.append(("brief", chat))
    p.send_digest = lambda chat=None: calls.append("digest")
    p.send_testers = lambda chat=None: None
    p.check_urgent = lambda now: calls.append("urgent")
    p.morning_tick(datetime(2026, 11, 18, 3, 0))                           # ночью (ср) — только проверка срочного
    p.morning_tick(datetime(2026, 11, 18, 3, 10))                          # не чаще раза в полчаса
    p.morning_tick(datetime(2026, 11, 18, 7, 30))                          # 07:30 рабочего дня — брифинг
    p.morning_tick(datetime(2026, 11, 18, 9, 0))                           # сводку в 09:00 второй раз не шлём
    assert calls == ["urgent", ("brief", 1), "urgent"]
    calls.clear()
    p.morning_tick(datetime(2026, 11, 21, 7, 31))                          # суббота — по умолчанию без брифинга
    assert ("brief", 1) not in calls
    p.cfg.brief_at = ""
    p.morning_tick(datetime(2026, 11, 19, 9, 0))                           # брифинг выключен — прежняя сводка
    assert calls[-1] == "digest"


def test_schedule_workday_weekend_and_timezone(tmp_path):
    from zoneinfo import ZoneInfo
    utc = ZoneInfo("UTC")
    sch = brief.schedule({})
    assert sch == {"time": "07:30", "days": [0, 1, 2, 3, 4], "tz": "", "every": "workdays"}
    p = brief.Prefs(tmp_path / "brief_prefs.json")
    p.set_schedule(1, "08:15", "workdays", tz="Europe/Moscow")             # UTC+3
    sch = brief.schedule(p.get(1))
    wed = datetime(2026, 11, 18, 5, 14, tzinfo=utc)                        # 08:14 в Москве — рано
    assert brief.due(sch, wed, "") == ""
    assert brief.due(sch, wed.replace(minute=15), "") == "2026-11-18"
    assert brief.due(sch, wed.replace(minute=15), "2026-11-18") == ""      # сегодня уже слали
    sat = datetime(2026, 11, 21, 6, 0, tzinfo=utc)
    assert brief.due(sch, sat, "") == ""                                   # выходной
    p.set_schedule(1, "08:15", "daily", tz="Europe/Moscow")
    assert brief.due(brief.schedule(p.get(1)), sat, "") == "2026-11-21"
    p.set_schedule(1, "08:15", "custom", days=[5], tz="America/New_York")  # смена пояса: UTC−5, только суббота
    sch = brief.schedule(p.get(1))
    assert sch["every"] == "custom" and brief.due(sch, sat, "") == ""      # в Нью-Йорке ещё 01:00
    assert brief.due(sch, datetime(2026, 11, 21, 13, 15, tzinfo=utc), "") == "2026-11-21"
    late_fri = datetime(2026, 11, 22, 1, 0, tzinfo=utc)                     # в UTC воскресенье, в Нью-Йорке — суббота
    assert brief.due(sch, late_fri, "") == "2026-11-21"
    for bad in (("25:00", "daily"), ("08:00", "weekly"), ("08:00", "custom")):
        with pytest.raises(ValueError):
            p.set_schedule(1, *bad)
    with pytest.raises(ValueError):
        p.set_schedule(1, "08:00", "daily", tz="Mars/Base")
    p.set(1, ["mail"])
    p.set_schedule(1, "06:00", "daily")
    assert p.get(1)["sources"] == ["mail"] and p.get(1)["time"] == "06:00"   # расписание и источники — отдельно


def test_digest_button_on_mail_opens_letter(tmp_path, monkeypatch):
    p = make(tmp_path, monkeypatch)
    x = {"kind": "mail", "key": "m1", "box": "gmail", "subject": "Договор", "url": "https://m/1"}
    p.digest.fresh([x], time.time())
    p.on_digest(1, "y:m1")
    assert p.sent[-1][1] == "Письмо: https://m/1"
    p.on_digest(1, "c:m1")
    assert p.digest.fresh([{"kind": "mail", "key": "m1"}], time.time()) == []
