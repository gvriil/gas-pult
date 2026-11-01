"""Условия использования: согласие с датой, смена версии, бот и панель до и после «Принимаю», «Отключить»."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import bot, terms, webapp, webauth
from gas_pult.config import Config
from gas_pult.people import People


def call(base, path, body=None, token=""):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r), r.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        return e.code, json.load(e), ""


def test_accept_and_version_change(tmp_path):
    p = People(tmp_path / "people.json", [1])
    p.add(2, "member", "Иван")
    assert not p.accepted(1) and not p.accepted(2) and not p.accepted(9)
    p.accept(1)
    p.accept(2)
    assert p.accepted(1) and p.accepted(2)
    assert not p.accepted(2, "2099-01-01")                       # новая версия — спросим заново
    rec = json.loads((tmp_path / "people.json").read_text())["2"]["terms"]
    assert rec["version"] == terms.VERSION and rec["at"] > 0     # у человека — в его записи, с датой
    own = json.loads((tmp_path / "terms.json").read_text())
    assert own["1"]["version"] == terms.VERSION                  # владелец — отдельным файлом, people.json прежний
    assert "1" not in json.loads((tmp_path / "people.json").read_text())
    assert (tmp_path / "terms.json").stat().st_mode & 0o777 == 0o600
    assert [x["id"] for x in p.list()] == [1, 2] and p.role(1) == "owner"
    p.add(2, "viewer", "Иван")                                # смена роли согласие не сбрасывает
    assert p.accepted(2) and p.role(2) == "viewer"
    p.accept(9)                                                  # без роли (ожидает входа): не появляется в людях
    assert p.accepted(9) and p.role(9) is None and 9 not in [x["id"] for x in p.list()]


def test_switch_off_removes_access_and_consent(tmp_path):
    p = People(tmp_path / "people.json", [1])
    p.add(2, "member")
    p.accept(2)
    p.remove(2)
    assert p.role(2) is None and not p.accepted(2)
    p.add(2, "member")                                           # пустили снова — условия заново
    assert not p.accepted(2)


@pytest.fixture
def pult(tmp_path):
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = type("C", (), {"owners": [1], "data": tmp_path, "region": "NL"})()
    p.people, p.logins, p.requests = People(tmp_path / "people.json", [1]), webauth.TgLogins(tmp_path / "tg.json"), {}
    p.waiting = {}
    p.sent, p.handled = [], []
    p.send = lambda chat, text, **kw: p.sent.append((chat, text, kw))
    p.to = lambda chat: (lambda text, **kw: p.sent.append((chat, text, kw)))
    p.api = lambda method, **kw: {}
    p.on_message = lambda m: p.handled.append(m.get("text"))
    return p


def cb(data):
    return {"callback_query": {"id": "q", "from": {"id": 1}, "message": {"chat": {"id": 1}}, "data": data}}


def test_bot_shows_terms_until_accepted(pult):
    p = pult
    p.handle({"message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "/start"}})
    assert not p.handled and "Условия использования" in p.sent[0][1] and terms.URL in p.sent[0][1]
    assert f"tm:{terms.VERSION}" in json.dumps(p.sent[0][2])
    p.sent.clear()
    p.handle(cb("set:notify=all"))
    assert "Условия использования" in p.sent[0][1]                     # любое действие до согласия — условия
    p.sent.clear()
    p.handle(cb("tm:2000-01-01"))
    assert "обновились" in p.sent[0][1] and not p.people.accepted(1)       # старая кнопка — не согласие
    p.sent.clear()
    p.handle(cb(f"tm:{terms.VERSION}"))
    assert p.people.accepted(1) and "Из какой страны" in p.sent[0][1]          # после условий — страна
    assert "cc:NL" in json.dumps(p.sent[0][2])
    p.sent.clear()
    p.handle({"message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "/start"}})
    assert not p.handled and "Из какой страны" in p.sent[0][1]                # без страны — снова выбор
    p.sent.clear()
    p.handle(cb("cc:NL"))
    assert p.people.country(1)["chosen"] == "NL" and p.sent[0][2]["reply_markup"] == bot.PHONE_KB
    p.sent.clear()
    bot.Pult.on_message(p, {"chat": {"id": 1}, "from": {"id": 1}, "text": "Позже"})
    assert p.sent[0][2]["reply_markup"] == bot.MENU                             # потом — обычное меню
    p.sent.clear()
    p.handle({"message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "/start"}})
    assert p.handled == ["/start"] and not p.sent


def test_bot_login_link_not_blocked_by_terms(pult):
    p = pult
    p.handle({"message": {"chat": {"id": 9}, "from": {"id": 9}, "text": "/start login_abc"}})
    assert p.handled == ["/start login_abc"] and not p.sent           # вход в панель — как раньше
    assert not p.need_terms({"callback_query": {"id": "q", "from": {"id": 9}, "data": "lg:ok:abc"}})


def test_bot_switch_off_with_confirmation(pult):
    p = pult
    p.people.add(2, "member", "Иван")
    p.switch_off(1, "2")
    assert "Отключить Иван?" in p.sent[-1][1] and "off:yes:2" in json.dumps(p.sent[-1][2])
    assert p.people.role(2) == "member"                               # без подтверждения — ничего
    p.switch_off(1, "yes:2")
    assert p.people.role(2) is None and "отключён" in p.sent[-1][1]
    p.switch_off(1, "yes:1")
    assert p.people.role(1) == "owner" and "нет в списке" in p.sent[-1][1]   # владельца не отключить


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    panel = webapp.Panel(Config(token="1:T", owners=[1]))
    panel.people.add(2, "member")
    panel.people.add(3, "viewer")
    for uid in (1, 2, 3):
        panel.people.set_country(uid, chosen="NL")
    monkeypatch.setattr(panel, "window", lambda wid: {"id": wid, "path": "/tmp", "name": "w"})
    monkeypatch.setattr(panel, "send", lambda w, text, mid="": False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_panel_terms_api(server):
    panel, base = server
    member, viewer = panel.auth.issue(2), panel.auth.issue(3)
    assert call(base, "/api/terms")[0] == 401
    code, meta, _ = call(base, "/api/meta", None, member)
    assert code == 200 and meta["terms"] == {"version": terms.VERSION, "accepted": False}
    code, d, _ = call(base, "/api/send", {"w": "@1", "text": "x"}, member)
    assert code == 403 and d["code"] == "terms"                        # до согласия — 403 с понятным кодом
    assert call(base, "/api/sessions", None, member)[1]["code"] == "terms"
    code, t, _ = call(base, "/api/terms", None, member)
    assert code == 200 and t["points"] == list(terms.POINTS) and t["url"] == terms.URL and not t["accepted"]
    assert call(base, "/api/terms/accept", {"version": "2000-01-01"}, member)[0] == 400
    code, t, _ = call(base, "/api/terms/accept", {"version": terms.VERSION}, member)
    assert code == 200 and t["accepted"] and t["at"] > 0 and panel.people.accepted(2)
    assert call(base, "/api/send", {"w": "@1", "text": "x"}, member)[0] == 200
    assert call(base, "/api/terms/accept", {"version": terms.VERSION}, viewer)[0] == 200   # наблюдатель тоже может
    assert call(base, "/api/send", {"w": "@1", "text": "x"}, viewer)[0] == 403              # но писать — нет


def test_panel_owner_by_code_and_switch_off(server):
    panel, base = server
    legacy = panel.auth.verify(*_code(panel))                          # вход кодом владельцу — согласие владельца
    assert call(base, "/api/people", None, legacy)[1]["code"] == "terms"
    call(base, "/api/terms/accept", {"version": terms.VERSION}, legacy)
    assert panel.people.accepted(1)
    member = panel.auth.issue(2)
    panel.people.accept(2)
    assert call(base, "/api/send", {"w": "@1", "text": "x"}, member)[0] == 200     # без tmux: send подменён
    code, d, _ = call(base, "/api/people/remove", {"id": 2}, legacy)   # «Отключить»
    assert code == 200 and 2 not in [p["id"] for p in d["people"]]
    assert call(base, "/api/send", {"w": "@1", "text": "x"}, member)[0] == 401     # доступ прекращён сразу


def _code(panel):
    rid, code = panel.auth.start()
    return rid, code
