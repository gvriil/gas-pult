"""Рабочий стол агентов за Caddy (#206): ``GET /api/gate/desktop`` — 204 только владельцу (forward_auth).

noVNC даёт полное управление браузером агентов со всеми входами — наружу его пускаем только владельца по cookie
входа панели; свежему входу — сперва код подтверждения (как для команд на сервере)."""

import urllib.request

from test_project_chats import call
from test_project_chats import server as server

from gas_pult import focus, webapp, webauth


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
    monkeypatch.setattr(webapp, "desktop_up", lambda port=None: False)
    code, e = call(base, "/api/desktop/open", {}, tok)
    assert code == 400 and "не запущен" in e["error"]
    monkeypatch.setattr(webapp, "desktop_up", lambda port=None: True)
    assert call(base, "/api/desktop/open", {}, tok)[1] == {"url": webapp.DESKTOP_URL}
    assert call(base, "/api/desktop/open", {}, p.auth.issue(2))[0] == 403     # участнику — нет
    assert call(base, "/api/meta", tok=tok)[1]["desktop"] is True


def test_desktop_up_probe():
    assert webapp.desktop_up(1) is False                                      # порт 1 никто не слушает
