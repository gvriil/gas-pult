"""Рабочий стол агентов за Caddy (#206): ``GET /api/gate/desktop`` — 204 только владельцу (forward_auth).

noVNC даёт полное управление браузером агентов со всеми входами — наружу его пускаем только владельца по cookie
входа панели; свежему входу — сперва код подтверждения (как для команд на сервере)."""

import urllib.request

from test_project_chats import call
from test_project_chats import server as server

from gas_pult import desktop, focus, webapp, webauth


def gate(base, cookie=""):
    req = urllib.request.Request(base + "/api/gate/desktop", headers={"Cookie": cookie} if cookie else {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_gate_only_owner_with_confirmed_session(server, monkeypatch):
    p, base, *_ = server
    owner, member, viewer = p.auth.issue(1), p.auth.issue(2), p.auth.issue(3)
    ck = lambda t: f"{webauth.COOKIE}={t}"                                    # noqa: E731
    assert gate(base) == 401                                                  # без входа
    assert gate(base, ck("wrong-token")) == 401
    assert gate(base, ck(owner)) == 403                                       # свежий вход — сперва код
    monkeypatch.setattr(p.auth, "needs_confirm", lambda tok, fresh=None: False)
    assert gate(base, ck(owner)) == 204
    assert gate(base, ck(p.auth.issue(webauth.LEGACY))) == 204               # вход кодом владельцу
    assert gate(base, ck(member)) == 403 and gate(base, ck(viewer)) == 403
    assert gate(base, f"{focus.COOKIE}=anything") == 401                   # фокус-ссылка — нет


def test_open_needs_desktop_and_confirm(server, monkeypatch):
    p, base, *_ = server
    tok = p.auth.issue(1)
    code, e = call(base, "/api/desktop/open", {}, tok)
    assert code == 403 and e.get("confirm") == "code"                         # свежий вход — код подтверждения
    monkeypatch.setattr(p.auth, "needs_confirm", lambda tok, fresh=None: False)
    monkeypatch.setattr(desktop, "desktop_up", lambda port=None: False)
    code, e = call(base, "/api/desktop/open", {}, tok)
    assert code == 400 and "не запущен" in e["error"]
    monkeypatch.setattr(desktop, "desktop_up", lambda port=None: True)
    assert call(base, "/api/desktop/open", {}, tok)[1]["url"] == webapp.DESKTOP_URL
    assert call(base, "/api/desktop/open", {}, p.auth.issue(2))[0] == 403     # участнику — нет
    assert call(base, "/api/meta", tok=tok)[1]["desktop"] is True


def test_desktop_up_probe():
    assert webapp.desktop_up(1) is False                                      # порт 1 никто не слушает


def test_pass_cookie_lets_iframe_in_without_panel_cookie(server, monkeypatch):
    """Mini App входит заголовком Telegram — iframe noVNC его не шлёт: пускает cookie-пропуск из «Рабочий стол»."""
    p, base, *_ = server
    tok = p.auth.issue(1)
    monkeypatch.setattr(p.auth, "needs_confirm", lambda tok, fresh=None: False)
    monkeypatch.setattr(desktop, "desktop_up", lambda port=None: True)
    req = urllib.request.Request(base + "/api/desktop/open", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={tok}"})
    with urllib.request.urlopen(req) as r:
        c = r.headers["Set-Cookie"]
    assert c.startswith(webapp.DESK_COOKIE + "=") and "Path=/desktop/" in c and "HttpOnly" in c and "Secure" in c
    pas = c.split(";")[0]
    assert gate(base, pas) == 204                                             # без cookie панели — пускает пропуск
    assert gate(base, f"{webapp.DESK_COOKIE}=wrong") == 401
    monkeypatch.setattr(p.people, "role", lambda uid: None)                   # роль сняли — пропуск не действует
    assert gate(base, pas) == 403


def test_desk_pass_expires():
    tok = webapp.desk_pass(1, now=1000.0)
    assert webapp.DESK_PASSES[tok][1] == 1000.0 + webapp.DESK_TTL
    webapp.desk_pass(1, now=1000.0 + webapp.DESK_TTL + 1)                      # просроченные — убираются
    assert tok not in webapp.DESK_PASSES


def test_ui_part_and_e2e():
    import importlib.util
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path

    web = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
    js = (web / "js" / "desktop.js").read_text(encoding="utf-8")
    assert '"/api/desktop/open"' in js and "Object.assign(window, { deskOpen" in js
    assert '"/api/desktop/open"' in (web / "index.html").read_text(encoding="utf-8").split("CONFIRM_PATHS")[1][:200]
    pytest = __import__("pytest")
    pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(web)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    spec = importlib.util.spec_from_file_location("desktop_demo", Path(__file__).parent / "e2e" / "desktop_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo")
    finally:
        srv.shutdown()


def test_tab_link_one_time_sets_first_party_pass(server, monkeypatch):
    """«Открыть в браузере» из Mini App: внешний браузер без cookie панели входит по одноразовой ссылке."""
    import http.client
    import urllib.parse

    p, base, *_ = server
    tok = p.auth.issue(1)
    monkeypatch.setattr(p.auth, "needs_confirm", lambda tok, fresh=None: False)
    monkeypatch.setattr(desktop, "desktop_up", lambda port=None: True)
    d = call(base, "/api/desktop/open", {}, tok)[1]
    assert d["tab"].startswith("/desktop-enter?t=")
    u = urllib.parse.urlparse(base)

    def enter(path):
        c = http.client.HTTPConnection(u.hostname, u.port)
        c.request("GET", path)                                                 # без cookie — как внешний браузер
        r = c.getresponse()
        return r.status, r.getheader("Location"), r.getheader("Set-Cookie") or ""

    code, loc, ck = enter(d["tab"])
    assert code == 303 and loc == webapp.DESKTOP_URL
    assert "SameSite=Lax" in ck and "Partitioned" not in ck and "Path=/desktop/" in ck
    assert gate(base, ck.split(";")[0]) == 204
    assert enter(d["tab"])[0] == 403                                           # второй раз — нет
    assert enter("/desktop-enter?t=wrong")[0] == 403
    assert call(base, "/api/desktop/open", {}, p.auth.issue(2))[0] == 403     # участнику ссылку не выдают


def test_ticket_expires():
    t = webapp.desk_ticket(1, now=1000.0)
    webapp.desk_ticket(1, now=1000.0 + webapp.TICKET_TTL + 1)
    assert t not in webapp.DESK_TICKETS


def test_desktop_clipboard_live():
    """Буфер «Браузера» вживую (владелец 23.11): свой Xvnc, Chrome и noVNC (tests/e2e/desktop_clipboard_live.py) —
    Ctrl/⌘+V кириллица и латиница, копия со стола, кнопка «Вставить» на телефоне; нет Xvnc/noVNC/Chrome — пропуск."""
    import importlib.util
    from pathlib import Path

    import pytest

    spec = importlib.util.spec_from_file_location("desktop_clipboard_live",
                                                  Path(__file__).parent / "e2e" / "desktop_clipboard_live.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    why = mod.ready()
    if why:
        pytest.skip(why)
    with mod.Stand() as st:
        assert mod.run(st) == []
