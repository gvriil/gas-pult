"""Уведомления на телефон (Web Push) без сторонних библиотек: VAPID и ES256 — системным openssl."""
import base64
import json
import shutil
import subprocess
import urllib.error

import pytest

from gas_pult import webpush

pytestmark = pytest.mark.skipif(not shutil.which("openssl"), reason="нет openssl")
EP = "https://fcm.googleapis.com/fcm/send/abc"


def raw_to_der(raw: bytes) -> bytes:
    def i(b):
        b = b.lstrip(b"\0") or b"\0"
        return b"\x02" + bytes([len(b) + (b[0] >> 7)]) + (b"\0" if b[0] & 0x80 else b"") + b
    body = i(raw[:32]) + i(raw[32:])
    return b"\x30" + bytes([len(body)]) + body


def test_key_is_private_and_jwt_verifies_with_openssl(tmp_path):
    h = webpush.Hub(tmp_path / "push")
    assert len(base64.urlsafe_b64decode(h.public_key() + "==")) == 65
    assert (h.key_file.stat().st_mode & 0o777) == 0o600
    head, body, sig = h.jwt("https://fcm.googleapis.com", "https://pult.example").split(".")
    (tmp_path / "sig").write_bytes(raw_to_der(base64.urlsafe_b64decode(sig + "==")))
    (tmp_path / "data").write_bytes(f"{head}.{body}".encode())
    subprocess.run(["openssl", "ec", "-in", str(h.key_file), "-pubout", "-out", str(tmp_path / "pub.pem")],
                   check=True, capture_output=True)
    r = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(tmp_path / "pub.pem"), "-signature",
                        str(tmp_path / "sig"), str(tmp_path / "data")], capture_output=True, text=True)
    assert "Verified OK" in r.stdout
    assert json.loads(base64.urlsafe_b64decode(body + "=="))["aud"] == "https://fcm.googleapis.com"


def test_only_known_push_services():
    assert webpush.allowed_endpoint(EP) and webpush.allowed_endpoint("https://web.push.apple.com/x")
    for bad in ("http://fcm.googleapis.com/x", "https://evil.example/fcm.googleapis.com", "https://127.0.0.1/x",
                "https://fcm.googleapis.com.evil.example/x", ""):
        assert not webpush.allowed_endpoint(bad), bad


def test_subscriptions_are_per_person_and_removable(tmp_path):
    h = webpush.Hub(tmp_path)
    with pytest.raises(ValueError):
        h.add(1, {"endpoint": "https://evil.example/x"})
    d = h.add(1, {"endpoint": EP}, "Android · Chrome")
    (dev,) = h.devices(1)
    assert dev["id"] == d["id"] and dev["label"] == "Android · Chrome" and dev["ok"] is None
    assert h.devices(2) == []                                         # чужие устройства не видны
    assert not h.remove(2, d["id"]) and h.remove(1, d["id"]) and h.devices(1) == []
    assert ((tmp_path / "subs.json").stat().st_mode & 0o777) == 0o600


def test_send_headers_and_gone_subscription_removed(tmp_path, monkeypatch):
    h = webpush.Hub(tmp_path)
    h.add(7, {"endpoint": EP}, "телефон")
    seen = []

    def fake(req, timeout):
        seen.append(req)
        raise urllib.error.HTTPError(req.full_url, 410, "Gone", {}, None)
    monkeypatch.setattr(webpush.OPENER, "open", fake)
    assert h.notify(7, "Пульт", "ждёт вашего ответа", w="@1", wait=True) == 1
    r = seen[0]
    assert r.get_method() == "POST" and r.data == b"" and r.headers["Ttl"] == "3600"
    assert r.headers["Authorization"].startswith("vapid t=") and ", k=" in r.headers["Authorization"]
    assert h.devices(7) == []                                         # 410 — подписка устарела и удалена
    items = h.pending(7, "dev1")
    assert [x["title"] for x in items] == ["Пульт"] and items[0]["w"] == "@1"
    assert h.pending(7, "dev1") == [] and len(h.pending(7, "dev2")) == 1   # каждое устройство забирает своё


@pytest.fixture
def server(tmp_path):
    import threading
    from http.server import ThreadingHTTPServer

    from gas_pult import webapp
    from gas_pult.config import Config
    panel = webapp.Panel(Config(token="1:T", owners=[1]))
    panel.push = webpush.Hub(tmp_path / "push")
    for uid, role in ((2, "member"), (3, "viewer")):
        panel.people.add(uid, role)
    for uid in (1, 2, 3):
        panel.people.accept(uid)
        panel.people.set_country(uid, chosen="NL")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, srv.server_address[1]
    srv.shutdown()


def req(port, path, method="GET", body=None, cookie=""):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, json.dumps(body) if body is not None else None,
              {"Cookie": cookie, "Content-Type": "application/json", "Host": "pult.example"})
    r = c.getresponse()
    out = (r.status, json.loads(r.read() or b"{}"))
    c.close()
    return out


def test_http_each_person_sees_only_own_devices(server, monkeypatch):
    from gas_pult import webauth
    panel, port = server
    monkeypatch.setattr(webpush.OPENER, "open", lambda req, timeout: type("R", (), {
        "status": 201, "__enter__": lambda s: s, "__exit__": lambda s, *a: None})())
    ck = {u: f"{webauth.COOKIE}={panel.auth.issue(u)}" for u in (1, 2, 3)}
    assert req(port, "/api/push/key")[0] == 401                               # без входа — нельзя
    st, d = req(port, "/api/push/key", cookie=ck[3])                          # наблюдатель — свои уведомления можно
    assert st == 200 and len(d["key"]) > 80
    st, d = req(port, "/api/push/subscribe", "POST", {"sub": {"endpoint": EP}, "label": "телефон"}, ck[3])
    assert st == 200, d
    assert req(port, "/api/push/subscribe", "POST", {"sub": {"endpoint": "https://evil.example/x"}}, ck[2])[0] == 400
    assert [x["label"] for x in req(port, "/api/push/devices", cookie=ck[3])[1]["devices"]] == ["телефон"]
    assert req(port, "/api/push/devices", cookie=ck[1])[1]["devices"] == []   # и владелец не видит чужих
    assert req(port, "/api/push/unsubscribe", "POST", {"id": d["id"]}, ck[1])[1] == {"ok": False}
    st, t = req(port, "/api/push/test", "POST", {}, ck[3])
    assert st == 200 and t["devices"] == 1 and t["list"][0]["ok"] is True
    assert req(port, "/api/push/last?dev=x", cookie=ck[3])[1]["items"][0]["title"] == "Проверка уведомлений"
    assert req(port, "/api/push/last?dev=x", cookie=ck[2])[1]["items"] == []


def test_bot_broadcast_and_answers_reach_owner_phone(tmp_path, monkeypatch):
    """Всё, что владелец получает в Telegram (bot.broadcast), и ответы сессий — и на телефон, если он включил."""
    from gas_pult import bot
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = type("C", (), {"data": tmp_path, "owners": [1]})()
    p.send = lambda *a, **k: None
    got = []
    monkeypatch.setattr(webpush.Hub, "notify",
                        lambda self, uid, title, body="", w="", wait=False: got.append((uid, title, body, w)))
    p.broadcast("⏳ [План] упёрлась в лимит подписки")
    assert got == []                                                   # нет устройств — ничего
    webpush.Hub(tmp_path / "push").add(1, {"endpoint": EP}, "телефон")
    p.broadcast("⏳ [План] упёрлась в лимит подписки")
    assert got == [(1, "Ладея", "[План] упёрлась в лимит подписки", "")]


def test_redirect_from_push_service_is_not_followed(tmp_path):
    """3xx от службы пуша — не идём по новому адресу (иначе обход фильтра адресов)."""
    import http.client
    h = webpush._NoRedirect()
    req = webpush.urllib.request.Request(EP, data=b"", method="POST")
    assert h.redirect_request(req, None, 307, "x", http.client.HTTPMessage(), "https://127.0.0.1/admin") is None


def test_settings_show_push_state_and_telegram_way_out():
    """Владелец 20.11: «опять только Telegram» — подписок не было («Включить» не нажимали). Состояние — сразу в подписи
    пункта «Уведомления»; из Telegram — «Открыть в браузере» (там ставят на экран «Домой» и включают)."""
    from pathlib import Path
    web = Path(__file__).resolve().parents[1] / "src/gas_pult/web/js"
    st = (web / "settings.js").read_text(encoding="utf-8")
    assert "sub: pushState()" in st and "на этом устройстве выключены — включить" in st
    assert "откройте Ладею значком с экрана «Домой»" in st
    js = (web / "push.js").read_text(encoding="utf-8")
    assert 'label: "Открыть в браузере"' in js and "tg.openLink(location.origin" in js
