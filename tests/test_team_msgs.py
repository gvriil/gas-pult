"""Сообщения команды в чат и «Сообщить об ошибке» (teammsg.py, владелец 22.11): видны в чате своего окна и
проекта и не видны чужой фокус-ссылке, в tmux не уходят; отчёт → задача, уведомление, «Приняли»; задачу закрыли →
«Исправлено»; лимит и права."""

import argparse
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import cli, focus, harness, tasks, teammsg, webapp, webauth
from gas_pult.config import Config

OWNER, VIEWER = 1, 2
UA_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Safari/604.1"
WINS = {"@5": {"id": "@5", "path": "/tmp/m", "name": "m", "sid": "s-five"},
        "@6": {"id": "@6", "path": "/tmp/n", "name": "n", "sid": "s-six"},
        "@7": {"id": "@7", "path": "/tmp/k", "name": "k", "sid": "s-seven"}}
PROJ_OF = {"@5": "p0000000001", "@6": "p0000000002", "@7": "p0000000001"}
LINKS = {"fc5": {"id": "f5", "w": "@5", "name": "Пять", "space": None},       # ссылка на сессию @5
         "fc6": {"id": "f6", "w": "@6", "name": "Шесть", "space": None},      # ссылка на сессию @6 (чужая для @5)
         "fcp": {"id": "fp", "w": "", "proj": "p0000000001", "name": "Проект", "space": None}}


class FakeHarness:
    name = "claude"

    def revision(self, *a, **k):
        return "rev1-1-1"

    def history(self, *a, **k):
        return [{"i": 0, "role": "user", "text": "привет", "ts": "2026-11-22 10:00"}], False


@pytest.fixture
def srv(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    p = webapp.Panel(Config(token="1:T", owners=[OWNER]))
    p.people.add(VIEWER, "viewer", "Наблюдатель")
    for uid in (OWNER, VIEWER):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    sent, told = [], []
    monkeypatch.setattr(p, "window", lambda wid: WINS.get(wid))
    monkeypatch.setattr(p.tmux, "window", lambda wid: WINS.get(wid))
    for name in ("paste", "send", "send_text", "keys"):              # в tmux — ничего
        if hasattr(p.tmux, name):
            monkeypatch.setattr(p.tmux, name, lambda *a, _n=name, **k: sent.append((_n, a)))
    monkeypatch.setattr(p, "project_data", lambda *a, **k: {"projects": {"p0000000001": {}, "p0000000002": {}}})
    monkeypatch.setattr(p, "project_of", lambda d, w: PROJ_OF.get(w["id"], ""))
    monkeypatch.setattr(p, "chat_title", lambda *a, **k: "Чат про фото")
    monkeypatch.setattr(p.pult, "broadcast", lambda text, *a, **k: told.append(text))
    monkeypatch.setattr(harness, "of", lambda w: FakeHarness())
    monkeypatch.setattr(p, "focus_rec", lambda c: LINKS[c] if c in LINKS else (_ for _ in ()).throw(focus.Gone("нет")))
    monkeypatch.setattr(p, "focus_owns", lambda r, wid: wid == r["w"] if not r.get("proj")
                        else PROJ_OF.get(wid) == r["proj"])
    s = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield {"base": f"http://127.0.0.1:{s.server_address[1]}", "owner": p.auth.issue(OWNER),
           "viewer": p.auth.issue(VIEWER), "p": p, "sent": sent, "told": told, "data": tmp_path}
    s.shutdown()


def call(srv, path, body=None, who="owner", ua=UA_IPHONE):
    hdr = {"User-Agent": ua, "Content-Type": "application/json"}
    if who in LINKS:
        hdr.update({"Cookie": f"{focus.COOKIE}={who}", focus.HEADER: "1"})
    else:
        hdr["Cookie"] = f"{webauth.COOKIE}={srv[who]}"
    data = json.dumps(body).encode() if body is not None else None
    try:
        r = urllib.request.urlopen(urllib.request.Request(srv["base"] + path, data, hdr))
    except urllib.error.HTTPError as e:
        r = e
    return (r.status if hasattr(r, "status") else r.code), json.loads(r.read() or b"{}")


def team_of(srv, w, who="owner"):
    code, out = call(srv, f"/api/history?w={w.replace('@', '%40')}", who=who)
    assert code == 200, out
    return [m["text"] for m in out.get("team", [])]


def test_team_say_visible_in_own_window_and_project_only(srv):
    assert call(srv, "/api/team/say", {"w": "@5", "text": "Окну пять"})[0] == 200
    assert call(srv, "/api/team/say", {"proj": "p0000000001", "text": "Проекту один"})[0] == 200
    assert call(srv, "/api/team/say", {"w": "@6", "text": "Окну шесть"})[0] == 200
    assert team_of(srv, "@5") == ["Окну пять", "Проекту один"]
    assert team_of(srv, "@7") == ["Проекту один"]                       # другое окно того же проекта
    assert team_of(srv, "@6") == ["Окну шесть"]
    # фокус-ссылки: своя сессия — свои; чужое окно — 403 и ни слова; ссылка на проект — окна проекта
    assert team_of(srv, "@5", "fc5") == ["Окну пять", "Проекту один"]
    code, out = call(srv, "/api/history?w=%406", who="fc5")
    assert code == 403 and "team" not in out
    assert team_of(srv, "@6", "fc6") == ["Окну шесть"]
    assert team_of(srv, "@7", "fcp") == ["Проекту один"]
    assert call(srv, "/api/history?w=%406", who="fcp")[0] == 403
    # «журнал не менялся» — сообщения команды всё равно приходят
    code, out = call(srv, "/api/history?w=%405&rev=rev1-1-1")
    assert out["same"] is True and [m["kind"] for m in out["team"]] == ["info", "info"]
    assert out["team"][0]["from"] == "Команда" and out["team"][0]["ts"]
    assert srv["sent"] == []                                             # в tmux и Claude — ничего


def test_team_say_rights_and_errors(srv):
    assert call(srv, "/api/team/say", {"w": "@5", "text": "т"}, who="viewer")[0] == 403
    assert call(srv, "/api/team/say", {"w": "@5", "text": "т"}, who="fc5")[0] == 403
    assert call(srv, "/api/team/say", {"w": "@9", "text": "т"})[0] == 404
    assert call(srv, "/api/team/say", {"proj": "p0000000009", "text": "т"})[0] == 404
    assert call(srv, "/api/team/say", {"w": "@5", "text": " "})[0] == 400
    assert call(srv, "/api/team/say", {"w": "@5", "text": "т", "kind": "spam"})[0] == 400


def test_team_msg_event_has_no_text(srv):
    call(srv, "/api/team/say", {"w": "@5", "text": "секретный текст команды"})
    log = (srv["data"] / "chat-events.jsonl").read_text(encoding="utf-8")
    assert '"team_msg"' in log and "секретный" not in log


def test_bug_report_task_notify_ack_and_fixed(srv):
    ctx = {"screen": "session · chat", "url": "/?session=@5", "size": "390×844 · 3x", "theme": "тёмная",
           "errors": ["js: x is undefined app.js:1"], "ui": ["10:00:00 Не отправлено"], "junk": "y" * 9000}
    code, out = call(srv, "/api/bug", {"w": "@5", "text": "Фото не уходит", "ctx": ctx}, who="fc5")
    assert code == 200, out
    assert out["ack"]["kind"] == "ack" and "Приняли" in out["ack"]["text"]
    t = srv["p"].tasks.get(out["task"])
    assert t["kind"] == "check" and t["status"] == "todo" and t["title"] == "Ошибка: Фото не уходит"
    assert (t["device"], t["browser"], t["proj"], t["chat"]) == ("iPhone", "Safari", "p0000000001", "@5")
    assert t["text"] == "Фото не уходит" and t["chat_title"] == "Чат про фото"
    rec = json.loads(Path(t["link"]).read_text(encoding="utf-8"))           # вложение — файл в данных пульта
    assert Path(t["link"]).parent == srv["data"] / teammsg.BUGS and oct(Path(t["link"]).stat().st_mode)[-3:] == "600"
    assert rec["ctx"]["theme"] == "тёмная" and "junk" not in rec["ctx"] and rec["ctx"]["errors"]
    assert len(srv["told"]) == 1 and "Фото не уходит" in srv["told"][0] and "iPhone" in srv["told"][0]
    assert team_of(srv, "@5", "fc5") == ["Приняли, сообщим, когда исправим."]
    assert team_of(srv, "@6", "fc6") == []                                  # чужой ссылке — ничего
    assert srv["sent"] == []
    # задачу закрыли — человеку в его чат «Исправлено»
    srv["p"].tasks.update(t["id"], {"status": "done"})
    got = team_of(srv, "@5", "fc5")
    assert got[-1] == "Исправлено: Фото не уходит. Проверьте, пожалуйста."
    srv["p"].tasks.update(t["id"], {"status": "todo"})
    srv["p"].tasks.update(t["id"], {"status": "done"})                      # снова закрыли — снова сообщение
    assert len(team_of(srv, "@5")) == 3


def test_bug_rate_limit_text_limit_and_rights(srv):
    for i in range(3):
        assert call(srv, "/api/bug", {"w": "@5", "text": f"раз {i}"}, who="fc5")[0] == 200
    code, out = call(srv, "/api/bug", {"w": "@5", "text": "четвёртый"}, who="fc5")
    assert code == 400 and "часто" in out["error"]
    assert call(srv, "/api/bug", {"w": "@5", "text": "другое устройство"}, who="fc5", ua="Mozilla/5.0 (Windows NT"
                " 10.0) Chrome/130.0 Safari/537.36")[0] == 200
    assert call(srv, "/api/bug", {"w": "@5", "text": "x" * 2001})[0] == 400
    assert call(srv, "/api/bug", {"w": "@5", "text": ""})[0] == 400
    assert call(srv, "/api/bug", {"w": "@6", "text": "чужое окно"}, who="fc5")[0] == 403
    assert call(srv, "/api/bug", {"w": "@9", "text": "нет окна"})[0] == 404
    assert call(srv, "/api/bug", {"w": "@5", "text": "наблюдатель тоже может"}, who="viewer")[0] == 200


def test_demo_link_cannot_report():
    from gas_pult.access import BUG, DEMO_POST, FOCUS_POST, OWNER_ONLY, SPACE_OK, TEAM_SAY
    assert BUG in FOCUS_POST and BUG in SPACE_OK and BUG not in DEMO_POST
    assert TEAM_SAY in OWNER_ONLY and TEAM_SAY not in FOCUS_POST and TEAM_SAY not in SPACE_OK


def test_for_window_space_and_restart(tmp_path):
    m = teammsg.TeamMsgs(tmp_path / teammsg.FILE)
    m.say(teammsg.target(w="@3", sid="conv-a"), "владельцу")
    m.say(teammsg.target(w="@3", sid="conv-b", space="alpha"), "пространству")
    assert [x["text"] for x in m.for_window({"id": "@3", "sid": "conv-a"})] == ["владельцу"]
    assert [x["text"] for x in m.for_window({"id": "@3", "sid": "conv-b", "space": "alpha"})] == ["пространству"]
    assert [x["text"] for x in m.for_window({"id": "@9", "sid": "conv-a"})] == ["владельцу"]   # перезапуск окна
    assert m.for_window({"id": "@3", "sid": "conv-z"}) == []            # тот же номер окна, другой разговор


def test_cli_chat_say(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))

    class T:
        session = "main"

        def windows(self):
            return [{"id": "@12", "name": "gas-pult", "sid": "s12"}]
    m = cli.cmd_chat_say(argparse.Namespace(action="say", window="main:gas-pult", folder="Обновили", rest=["панель"],
                                            kind="info"), tmux=T())
    assert m["w"] == "@12" and m["text"] == "Обновили панель" and "окно @12" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.cmd_chat_say(argparse.Namespace(action="say", window="p0000000009", folder="т", rest=[], kind="info"))
    got = teammsg.TeamMsgs(tmp_path / teammsg.FILE).for_window({"id": "@12", "sid": "s12"})
    assert [x["text"] for x in got] == ["Обновили панель"]


def test_tasks_keep_bug_fields(tmp_path):
    t = tasks.Tasks(tmp_path / "tasks.json")
    x = t.add({"title": "Ошибка: а", "kind": "check", "link": "/x", "next": "n", "text": "строка 1\nстрока 2",
               "device": "iPhone", "browser": "Safari", "proj": "p1", "team_to": "{}"})
    assert x["text"] == "строка 1\nстрока 2" and x["device"] == "iPhone"
    t.update(x["id"], {"status": "done"})                                   # битый адрес — без сообщения и ошибки
    assert not (tmp_path / teammsg.FILE).exists()


def test_ui_bug_button_and_team_card():
    web = Path(webapp.__file__).with_name("web")
    html = (web / "index.html").read_text(encoding="utf-8")
    assert 'id="bugBtn"' in html and "bug: '" in html and 'part("bugreport")' in html
    assert "class=\"tmsg" in html and "setTeam(h.team)" in html
    assert len(html.encode()) < 770000
    js = (web / "js/bugreport.js").read_text(encoding="utf-8")
    assert '"/api/bug"' in js and "import " not in js                       # без зависимостей
