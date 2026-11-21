"""Уведомления, часть B: каналы «На телефон / Telegram / Почта», выбор событий, одна точка доставки (notifyroute.py).

Владелец (через штаб): Telegram у владельца не выключаем, пока он не напишет «пуш дошёл» — по умолчанию всё включено,
выключает только он сам на экране «Уведомления»."""
import json
import os
from pathlib import Path

import pytest

from gas_pult import notifyroute, webpush
from gas_pult.notifyroute import Store, route

EP = "https://fcm.googleapis.com/fcm/send/abc"
WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"


def test_defaults_keep_old_behaviour():
    """Ничего не выбрано — как раньше: Telegram и телефон (если есть устройство), почта — только если включена."""
    assert route(None, "error", push=False, email=False) == {"telegram"}
    assert route(None, "answer", push=True, email=False) == {"telegram", "push"}
    assert route(None, "brief", push=True, email=True) == {"telegram", "push", "email"}


def test_rules_nothing_gets_lost():
    off = {"telegram": False}
    assert route(off, "error", push=True, email=False) == {"push"}
    assert route(off, "error", push=False, email=False) == {"telegram"}      # других каналов нет — Telegram
    assert route(off, "dialog", push=True, email=False, action=True) == {"telegram", "push"}   # кнопки — в Telegram
    assert route(off, "answer", push=False, email=True) == {"telegram"}      # ответы письмом не шлём
    muted = {"events": {"people": False}}
    assert route(muted, "people", push=True, email=True) == set()            # событие выключено — тишина
    assert route(muted, "people", push=True, email=True, action=True) == {"telegram", "push", "email"}
    assert route(None, "непонятное", push=False, email=False) == {"telegram"}  # неизвестный вид — как сбой


def test_store_is_private_and_validates(tmp_path):
    s = Store(tmp_path / "n.json")
    assert s.get(1) == {"push": True, "telegram": True, "events": dict.fromkeys(notifyroute.EVENTS, True)}
    s.set(1, {"telegram": False, "events": {"answer": False}})
    assert s.get(1)["telegram"] is False and s.get(1)["events"]["answer"] is False
    assert s.get(2)["telegram"] is True                                       # у каждого свои
    assert oct(os.stat(tmp_path / "n.json").st_mode & 0o777) == "0o600"
    for bad in ({"telegram": "нет"}, {"events": {"всё": False}}, {"events": {"answer": 1}}, []):
        with pytest.raises(ValueError):
            s.set(1, bad)


def bot_for(tmp_path, monkeypatch):
    from gas_pult import bot
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = type("C", (), {"data": tmp_path, "owners": [1]})()
    sent, pushed = [], []
    p.send = lambda chat, text, **kw: sent.append((chat, text, "reply_markup" in kw)) or {}
    monkeypatch.setattr(webpush.Hub, "notify",
                        lambda self, uid, title, body="", w="", wait=False: pushed.append((uid, body)))
    return p, sent, pushed


def test_bot_broadcast_goes_only_to_chosen_channels(tmp_path, monkeypatch):
    p, sent, pushed = bot_for(tmp_path, monkeypatch)
    webpush.Hub(tmp_path / "push").add(1, {"endpoint": EP}, "телефон")
    p.broadcast("⚠️ сбой")
    assert sent == [(1, "⚠️ сбой", False)] and pushed == [(1, "сбой")]       # по умолчанию — как раньше
    sent.clear(), pushed.clear()
    Store(tmp_path / "notify_channels.json").set(1, {"telegram": False})
    p.broadcast("⚠️ сбой")
    assert sent == [] and pushed == [(1, "сбой")]                            # Telegram выключен — только телефон
    p.broadcast("🔐 просит доступ", kind="people", reply_markup={"inline_keyboard": []})
    assert sent == [(1, "🔐 просит доступ", True)]                           # кнопки решения — в Telegram всегда
    sent.clear(), pushed.clear()
    Store(tmp_path / "notify_channels.json").set(1, {"events": {"brief": False}})
    p.broadcast("🗓 по расписанию", kind="brief")
    assert sent == [] and pushed == []                                       # событие выключено


def test_bot_answers_follow_channels(tmp_path, monkeypatch):
    p, _, _ = bot_for(tmp_path, monkeypatch)
    webpush.Hub(tmp_path / "push").add(1, {"endpoint": EP}, "телефон")
    Store(tmp_path / "notify_channels.json").set(1, {"telegram": False})
    assert p.channels(1, "answer") == {"push"}
    Store(tmp_path / "notify_channels.json").set(1, {"events": {"answer": False}})
    assert p.channels(1, "answer") == set()


def req(port, path, method="GET", body=None, cookie=""):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, json.dumps(body) if body is not None else None,
              {"Cookie": cookie, "Content-Type": "application/json", "Host": "pult.example"})
    r = c.getresponse()
    out = (r.status, json.loads(r.read() or b"{}"))
    c.close()
    return out


@pytest.fixture
def server(tmp_path):
    import threading
    from http.server import ThreadingHTTPServer

    from gas_pult import webapp
    from gas_pult.config import Config
    panel = webapp.Panel(Config(token="1:T", owners=[1]))
    panel.push = webpush.Hub(tmp_path / "push")
    panel.people.add(3, "viewer")
    for uid in (1, 3):
        panel.people.accept(uid)
        panel.people.set_country(uid, chosen="NL")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, srv.server_address[1]
    srv.shutdown()


def test_http_owner_sets_channels_others_cannot(server):
    from gas_pult import webauth
    panel, port = server
    ck = {u: f"{webauth.COOKIE}={panel.auth.issue(u)}" for u in (1, 3)}
    assert req(port, "/api/notify/prefs")[0] == 401
    st, d = req(port, "/api/notify/prefs", cookie=ck[1])
    assert st == 200 and d["owner"] is True and d["telegram"] is True
    assert [e["id"] for e in d["events"]] == list(notifyroute.EVENTS)
    assert d["email"] == {"can": False, "addr": False, "on": False}         # почта на сервере не настроена
    st, d = req(port, "/api/notify/prefs", "POST", {"telegram": False, "events": {"answer": False}}, ck[1])
    assert st == 200 and d["telegram"] is False and d["events"][0]["on"] is False
    assert req(port, "/api/notify/prefs", "POST", {"telegram": "да"}, ck[1])[0] == 400
    st, d = req(port, "/api/notify/prefs", cookie=ck[3])                   # наблюдатель видит только своё
    assert st == 200 and d["owner"] is False
    assert req(port, "/api/notify/prefs", "POST", {"telegram": False}, ck[3])[0] == 403
    assert Store(panel.cfg.data / "notify_channels.json").get(3)["telegram"] is True


def test_screen_has_channels_and_events():
    js = (WEB / "js/push.js").read_text(encoding="utf-8")
    assert '{ head: "Куда присылать" }' in js and '{ head: "О чём сообщать" }' in js
    assert 'label: "Telegram"' in js and 'label: "Почта"' in js and '"/api/notify/prefs"' in js
    assert "сообщения с кнопками решений всё равно придут туда" in js
