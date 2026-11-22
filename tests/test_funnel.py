"""События продукта и воронка (funnel.py): без персональных данных, первый ответ — один раз, свод и права API."""

import json
import os
import stat

from test_people_login import call, server  # noqa: F401

from gas_pult import funnel

DAY = 86400
T0 = 1_790_000_000.0                                  # 21.09.2026, UTC


def test_events_have_no_personal_data(tmp_path):
    f = funnel.Funnel(tmp_path, clock=lambda: T0)
    uid, text = 123456789, "секретный вопрос про выручку ООО Ромашка"
    f.login(uid, "", "telegram")
    f.send(uid, "shop-1", "panel")
    f.decide(uid, True, "", "drafts")
    f.decide(uid, False, "", "not a word!")              # «via» — только короткое слово, иначе поля нет
    raw = (tmp_path / funnel.FILE).read_text()
    assert str(uid) not in raw and text not in raw
    rows = [json.loads(x) for x in raw.splitlines()]
    assert [r["ev"] for r in rows] == ["login", "send", "yes", "no"]
    assert all(set(r) <= {"t", "ev", "v", "u", "sp", "via"} and r["v"] == funnel.SCHEMA for r in rows)
    assert len({r["u"] for r in rows}) == 1 and len(rows[0]["u"]) == 16
    assert rows[1]["sp"] == "shop-1" and "via" not in rows[3]
    for name in (funnel.FILE, funnel.SALT, funnel.SEEN):
        assert stat.S_IMODE(os.stat(tmp_path / name).st_mode) == 0o600
    # отпечаток зависит от соли: другой сервер — другой отпечаток того же человека
    other = tmp_path / "other"
    assert funnel.Funnel(other).who(uid) != f.who(uid)
    assert f.event("login", None) is None and f.event("chat", uid) is None     # без человека и чужое событие — нет
    assert f.event("send", uid, "../etc")["sp"] == ""                       # пространство — только имя


def test_first_reply_once_per_person(tmp_path):
    now = [T0]
    f = funnel.Funnel(tmp_path, clock=lambda: now[0])
    assert f.answered(5, [{"role": "assistant", "text": "x", "ts": "2030-01-01 00:00"}]) is None   # не писал — нет
    f.send(5)
    old = {"role": "assistant", "text": "старый", "ts": "2020-01-01 00:00"}
    assert f.answered(5, [old]) is None                                  # ответ до сообщения — не ответ ему
    new = {"role": "assistant", "text": "ответ", "ts": "2099-01-01 00:00"}
    assert f.answered(5, [old, new])["ev"] == "first_reply"
    assert f.answered(5, [new]) is None and f.replied(5) is None          # второй раз — нет
    g = funnel.Funnel(tmp_path)                                           # другой процесс (бот) — тоже помнит
    assert g.replied(5) is None and g.replied(6)["ev"] == "first_reply"
    evs = [r["ev"] for r in f.read()]
    assert evs.count("first_reply") == 2


def test_choice_yes_no():
    ask = {"options": [{"key": "yes", "send": {"n": "1"}}, {"key": "yes-session", "send": {"n": "2"}},
                       {"key": "no-tell", "send": {"n": "3"}}, {"key": "details", "send": {"show": True}},
                       {"key": "deny", "send": {"key": "Escape"}}]}
    assert funnel.choice(ask, n="1") == "yes" and funnel.choice(ask, n="2") == "yes"
    assert funnel.choice(ask, n="3") == "no" and funnel.choice(ask, key="Escape") == "no"
    assert funnel.choice(ask, n="9") is None and funnel.choice(None, n="1") is None
    assert funnel.choice(ask) is None


def fake(tmp_path):
    """Поддельный журнал: 4 вошли, 3 получили ответ (один — без входа), 2 из них сказали «Да»."""
    rows = []

    def ev(day, e, u, sp=""):
        rows.append({"t": T0 + day * DAY, "ev": e, "v": 1, "u": u, "sp": sp})
    for u in ("a", "b", "c", "d"):
        ev(0, "login", u)
    ev(1, "send", "a")
    ev(1, "first_reply", "a")
    ev(1, "first_reply", "b")
    ev(2, "first_reply", "z")                       # без входа за срок — в воронку не попадает
    ev(2, "yes", "a")
    ev(2, "yes", "a")
    ev(2, "no", "b")
    ev(2, "yes", "z")
    ev(0, "login", "s", "shop")
    ev(-40, "login", "old")                         # старше срока
    p = tmp_path / funnel.FILE
    p.write_text("".join(json.dumps(r) + "\n" for r in rows) + "битая строка\n")
    return funnel.Funnel(tmp_path)


def test_report_on_fake_journal(tmp_path):
    f = fake(tmp_path)
    r = funnel.report(f.read(), days=30, space="", now=T0 + 3 * DAY)
    assert [(s["ev"], s["people"]) for s in r["steps"]] == [("login", 4), ("first_reply", 2), ("yes", 1)]
    assert r["steps"][0]["conv"] is None and r["steps"][1]["conv"] == 0.5 and r["steps"][2]["conv"] == 0.5
    assert r["steps"][2]["of_first"] == 0.25
    assert r["events"] == {"login": 4, "send": 1, "first_reply": 3, "yes": 3, "no": 1}
    assert [d["day"] for d in r["by_day"]] == ["2026-09-21", "2026-09-22", "2026-09-23"]
    assert r["by_day"][0]["login"] == 4 and r["by_day"][2]["yes"] == 2
    every = funnel.report(f.read(), days=30, now=T0 + 3 * DAY)
    assert every["steps"][0]["people"] == 5                                 # все пространства
    assert funnel.report(f.read(), days=30, space="shop", now=T0 + 3 * DAY)["steps"][0]["people"] == 1
    assert funnel.report(f.read(), days=60, space="", now=T0 + 3 * DAY)["steps"][0]["people"] == 5
    out = funnel.text(r)
    assert "вошли" in out and "50% от прошлого шага" in out and "По дням" in out


def test_prune_keeps_days(tmp_path):
    now = [T0]
    f = funnel.Funnel(tmp_path, keep_days=10, clock=lambda: now[0])
    f.login(1)
    now[0] = T0 + 11 * DAY
    f.login(2)
    assert len(f.read()) == 1                                             # старше 10 дней — срезано


def test_api_funnel_owner_only_and_login_event(server):  # noqa: F811
    panel, base = server
    owner, member = panel.auth.issue(1), panel.auth.issue(2)
    assert call(base, "/api/funnel")[0] == 401
    assert call(base, "/api/funnel", None, member)[0] == 403
    assert call(base, "/api/send", {"w": "@1", "text": "привет агенту", "id": "m1"}, member)[0] == 200
    st, r, _ = call(base, "/api/funnel?days=7", None, owner)
    assert st == 200 and r["days"] == 7 and r["events"]["send"] == 1 and [s["ev"] for s in r["steps"]] == \
        ["login", "first_reply", "yes"]
    raw = (panel.cfg.data / funnel.FILE).read_text()
    assert "привет" not in raw and '"u": "2"' not in raw
    # вход через Telegram — событие login с этим способом
    _, d, _ = call(base, "/api/login/tg", {})
    panel.logins.decide(d["link"].rsplit("login_", 1)[1], 2, True)
    assert call(base, "/api/login/tg?id=" + d["id"])[1]["state"] == "ok"
    logins = [x for x in panel.funnel.read() if x["ev"] == "login"]
    assert logins and logins[-1]["via"] == "telegram" and logins[-1]["u"] == panel.funnel.who(2)
    assert call(base, "/api/funnel?space=bad_slug!", None, owner)[0] == 400
