import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import bot, webapp, webauth
from gas_pult.config import Config
from gas_pult.people import People, allowed


def test_roles_and_owner_protection(tmp_path):
    p = People(tmp_path / "people.json", [1])
    assert p.role(1) == "owner" and p.role(2) is None and p.role("x") is None
    p.add(2, "member", "Алексей", "alexey")
    p.add(3, "viewer")
    assert p.role(2) == "member" and p.role(3) == "viewer"
    assert (tmp_path / "people.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        p.add(1, "viewer")
    with pytest.raises(ValueError):
        p.add(4, "owner")
    p.remove(2)
    assert p.role(2) is None
    assert allowed("member", "viewer") and not allowed("viewer", "member") and not allowed(None, "viewer")


def test_telegram_login_flow(tmp_path):
    lg = webauth.TgLogins(tmp_path / "tg.json")
    rid, nonce = lg.start("1.2.3.4", "Chrome")
    assert rid != nonce and lg.poll(rid) == ("wait", None)
    assert lg.poll(nonce)[0] == "expired"                  # по ссылке из Telegram опросить нельзя
    assert lg.info(nonce)["ip"] == "1.2.3.4"
    assert lg.decide(nonce, 42, True) and not lg.decide(nonce, 43, True)   # решение — один раз
    assert lg.poll(rid) == ("ok", 42) and lg.poll(rid)[0] == "expired"     # вход гасится после выдачи
    rid2, nonce2 = lg.start()
    lg.decide(nonce2, 42, False)
    assert lg.poll(rid2) == ("no", None)
    rid3, nonce3 = lg.start()
    d = json.loads((tmp_path / "tg.json").read_text())
    d[nonce3]["exp"] = time.time() - 1
    (tmp_path / "tg.json").write_text(json.dumps(d))
    assert lg.poll(rid3)[0] == "expired" and lg.info(nonce3) is None


def test_sessions_carry_person(tmp_path):
    a = webauth.Auth(tmp_path / "s.json")
    t = a.issue(42, "ua")
    assert a.uid(t) == 42 and a.uid("nope") is None and a.check(t)


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    panel = webapp.Panel(Config(token="1:T", owners=[1]))
    panel.people.add(2, "member")
    panel.people.add(3, "viewer")
    monkeypatch.setattr(panel, "bot_username", lambda: "test_bot")
    monkeypatch.setattr(panel, "window", lambda wid: {"id": wid, "path": "/tmp", "name": "w"})
    monkeypatch.setattr(panel, "send", lambda w, text: None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(base, path, body=None, token=""):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r), r.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        return e.code, json.load(e), ""


def test_access_by_role(server):
    panel, base = server
    owner, member, viewer = (panel.auth.issue(u) for u in (1, 2, 3))
    assert call(base, "/api/people")[0] == 401                          # не вошёл
    assert call(base, "/api/send", {"w": "@1", "text": "x"}, viewer)[0] == 403     # наблюдатель не пишет
    assert call(base, "/api/send", {"w": "@1", "text": "x"}, member)[0] == 200     # участник пишет
    assert call(base, "/api/people", None, member)[0] == 403                       # люди — только владельцу
    assert call(base, "/api/run", {"w": "@1", "i": 0, "sha": "x"}, member)[0] == 403
    assert call(base, "/api/people", None, owner)[0] == 200
    panel.people.remove(2)
    assert call(base, "/api/send", {"w": "@1", "text": "x"}, member)[0] == 401     # убрали — вход перестал работать


def test_login_through_telegram_end_to_end(server):
    panel, base = server
    code, d, _ = call(base, "/api/login/tg", {})
    assert code == 200 and d["link"].startswith("https://t.me/test_bot?start=login_")
    nonce = d["link"].rsplit("login_", 1)[1]
    assert call(base, "/api/login/tg?id=" + d["id"])[1]["state"] == "wait"
    panel.logins.decide(nonce, 2, True)                                   # человек нажал «Войти» в Telegram
    code, r, cookie = call(base, "/api/login/tg?id=" + d["id"])
    assert r["state"] == "ok" and webauth.COOKIE in cookie
    token = cookie.split("=", 1)[1].split(";", 1)[0]
    assert panel.auth.uid(token) == 2 and call(base, "/api/meta", None, token)[1]["role"] == "member"


def test_bot_asks_confirmation_or_owner(monkeypatch, tmp_path):
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = type("C", (), {"owners": [1]})()
    p.people, p.logins, p.requests = People(tmp_path / "people.json", [1]), webauth.TgLogins(tmp_path / "tg.json"), {}
    sent = []
    p.to = lambda chat: (lambda text, **kw: sent.append((chat, text, kw)))
    p.broadcast = lambda text, **kw: sent.append(("owners", text, kw))
    _, nonce = p.logins.start("1.2.3.4", "Chrome")
    p.login_request({"from": {"id": 9, "first_name": "Иван", "username": "ivan"}, "chat": {"id": 9}}, nonce)
    assert sent[0][0] == 9 and "нет доступа" in sent[0][1]
    assert sent[1][0] == "owners" and "pp:member:9" in json.dumps(sent[1][2], ensure_ascii=False)
    p.people.add(9, "member")
    sent.clear()
    p.login_request({"from": {"id": 9}, "chat": {"id": 9}}, nonce)
    assert "Войти в панель" in sent[0][1] and f"lg:ok:{nonce}" in json.dumps(sent[0][2])
    assert bot.public({"message": {"text": "/start login_x"}}) and not bot.public({"message": {"text": "привет"}})
    assert bot.public({"callback_query": {"data": "lg:ok:x"}})
    assert not bot.public({"callback_query": {"data": "pp:member:1"}})          # раздавать доступ — только владелец
