"""Приглашение тестировщика /invite/<код> (задача 31, п. 4): 24 часа, один вход, пространство и роль; вход через
Telegram по нему — доступ сразу, без кнопки владельца; отзыв — gas-pult invite revoke."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import bot, cli, invites, tenants, webapp, webauth
from gas_pult.config import Config

OWNER, TESTER = 7201, 7202


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    root = tmp_path / "tenants"
    monkeypatch.setenv("GAS_PULT_TENANTS_ROOT", str(root))
    (root / "demo").mkdir(parents=True)
    (root / tenants.MARKER).write_text("{}")
    (root / "demo" / tenants.META).write_text(json.dumps({"title": "Демо для кафе"}))
    return tmp_path


def test_lifecycle(dirs):
    code = invites.create("demo")
    assert invites.CODE.match(code)
    raw = invites.store().read_text()
    assert code not in raw and code[:invites.HINT] in raw          # в файле — только хеш и первые знаки
    assert invites.store().stat().st_mode & 0o777 == 0o600
    assert invites.check(code)["tenant"] == "demo"
    assert invites.redeem(code, 5) == {"tenant": "demo", "role": "member"}
    assert invites.redeem(code, 6) is None and invites.check(code) is None     # один раз
    assert invites.listing()[0]["state"] == "used"
    late = invites.create("demo", "viewer", ttl=-1)
    assert invites.check(late) is None and invites.redeem(late, 7) is None     # срок вышел
    c3 = invites.create("demo")
    assert invites.revoke(c3[:invites.HINT]) == c3[:invites.HINT]
    assert invites.check(c3) is None
    for bad in ("", "x", "../../etc", "a" * 100):
        assert invites.check(bad) is None and invites.redeem(bad, 1) is None
    with pytest.raises(ValueError):
        invites.create("../x")
    with pytest.raises(ValueError):
        invites.create("demo", "owner")                              # владельцем не пригласить
    with pytest.raises(ValueError):
        invites.revoke("abc")


def serve(p):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def req(base, path, body=None, token=""):
    r = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                               {"Cookie": f"{webauth.COOKIE}={token}"} if token else {})
    try:
        x = urllib.request.build_opener(NoRedirect).open(r)
    except urllib.error.HTTPError as e:
        x = e
    raw = x.read()
    return x.code if hasattr(x, "code") else x.status, x.headers, json.loads(raw) if raw[:1] in (b"{", b"[") else raw


def test_web_flow():
    p = webapp.Panel(Config(token="1:T", owners=[OWNER], region="NL"))
    p.people.accept(OWNER)
    p.people.set_country(OWNER, chosen="NL")
    p.bot_username = lambda: "test_bot"                             # без похода в Telegram
    srv, base = serve(p)
    try:
        code = invites.create("demo")
        st, h, _ = req(base, f"/invite/{code}")
        assert st == 302 and h["Location"] == f"/?invite={code}" and "noindex" in h["X-Robots-Tag"]
        assert req(base, f"/api/invite?code={code}")[2] == {"ok": True, "title": "Демо для кафе"}
        assert req(base, "/api/invite?code=nope-nope-nope-nope")[2] == {"ok": False}
        assert req(base, "/api/login/tg", {"invite": "nope-nope-nope-nope"})[0] == 400
        st, _, d = req(base, "/api/login/tg", {"invite": code})
        assert st == 200 and "login_" in d["link"]
        nonce = d["link"].split("login_")[1]
        assert p.logins.info(nonce)["invite"] == code
        assert req(base, "/api/login/tg", {})[0] == 200                  # обычный вход — как раньше
        # владелец создаёт приглашение в панели; без входа — нельзя
        tok = p.auth.issue(OWNER)
        st, _, d = req(base, "/api/invite/new", {"space": "demo"}, tok)
        assert st == 200 and d["path"].startswith("/invite/") and invites.check(d["path"].split("/")[-1])
        assert req(base, "/api/invite/new", {"space": "demo"})[0] == 401
        assert req(base, "/api/invite/new", {"space": "../x"}, tok)[0] == 400
    finally:
        srv.shutdown()


class FakeApi:
    def __init__(self):
        self.calls = []

    def __call__(self, method, files=None, **params):
        self.calls.append((method, params))
        return {}

    def redact(self, text):
        return str(text)

    def texts(self, chat=None):
        return [x.get("text", "") for m, x in self.calls
                if m == "sendMessage" and (chat is None or x["chat_id"] == chat)]


def test_bot_grants_at_once_and_only_once():
    p = bot.Pult(Config(token="t", owners=[1], session="test"))
    p.api = FakeApi()
    code = invites.create("demo")
    _, nonce = p.logins.start("1.2.3.4", "Safari", invite=code)
    u = {"id": TESTER, "first_name": "Тест", "username": "tester"}
    p.login_request({"from": u, "chat": {"id": TESTER}}, nonce)
    assert p.people.role(TESTER) == "member" and p.people.tenant(TESTER) == "demo"
    assert any("Войти в панель" in t for t in p.api.texts(TESTER))          # сразу — подтверждение входа
    assert any("по приглашению" in t for t in p.api.texts(1))               # владельцу — уведомление
    assert not any("просит доступ" in t for t in p.api.texts(1))
    # второй человек по тому же коду — обычный запрос владельцу, без доступа
    _, n2 = p.logins.start("1.2.3.5", "Chrome", invite=code)
    p.login_request({"from": {"id": TESTER + 1, "first_name": "Другой"}, "chat": {"id": TESTER + 1}}, n2)
    assert p.people.role(TESTER + 1) is None
    assert any("просит доступ" in t for t in p.api.texts(1))


def test_cli(capsys):
    cli.main(["invite", "create", "demo", "--url", "https://panel.example"])
    out = capsys.readouterr().out
    link = next(x for x in out.split() if x.startswith("https://panel.example/invite/"))
    code = link.rsplit("/", 1)[1]
    assert invites.check(code)
    cli.main(["invite", "list"])
    assert code[:invites.HINT] in capsys.readouterr().out
    cli.main(["invite", "revoke", code[:invites.HINT]])
    assert invites.check(code) is None
    with pytest.raises(SystemExit):
        cli.main(["invite", "create", "Плохое имя"])
