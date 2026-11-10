"""Шторка «Нужен вход» (logins.py): образцы экранов входа, поле login в /api/screen и /api/tty — только владельцу,
/api/login/code — одна строка в окно, /api/login/check — проверка по виду входа. Ссылки и коды — заведомо поддельные."""

import contextlib
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import focus, logins, webapp, webauth
from gas_pult.config import Config

# Ссылки собраны из частей, чтобы сканеры не принимали образцы за настоящие.
CLAUDE_URL = ("https://claude.ai/oauth/authorize?code=true&client_id=" + "0" * 8
              + "-demo&response_type=code&redirect_uri=")
CLAUDE = [
    " Claude Code can be used with your Claude subscription or billed based on API usage.",
    "",
    " Browser didn't open? Use the url below to sign in (c to copy)",
    "",
    CLAUDE_URL + "https%3A%2F%2Fconsole.anthropic.com%2Foauth%2Fcode%2Fcallback"
    "&scope=org%3Acreate_api_key+user%3Aprofi",
    "le+user%3Ainference&code_challenge=" + "x" * 20 + "&state=" + "y" * 12,
    "",
    " Paste code here if prompted >",
]
GH = [
    "$ gh auth login --web",
    "! First copy your one-time code: " + "AB12" + "-" + "CD34",
    "Open this URL to continue in your web browser: https://github.com/login/device",
]
DEVICE = [
    "To sign in, use a web browser to open the page https://example.invalid/devicelogin and enter the code "
    + "WXYZ" + "-" + "9876" + " to authenticate.",
]
MCP = [
    " Authenticating with notion…",
    " · A browser window will open for authentication",
    " If your browser doesn't open automatically, copy this URL manually:",
    " https://mcp.example.invalid/authorize?response_type=code&client_id=demo&redirect_uri=http%3A%2F%2Flocalhost",
    " If the redirect page fails to load, paste the URL here:",
    " URL >",
]
ANSWER = [
    "● Подробности — в документации: https://docs.python.org/3/library/re.html",
    "  Claude Code продолжит после ответа.",
    "",
    "❯ ",
]


def test_detect_claude_login_with_wrapped_url():
    d = logins.detect(CLAUDE)
    assert d["kind"] == "claude" and d["wants"] == "code" and d["code"] == ""
    assert d["url"].startswith(CLAUDE_URL) and d["url"].endswith("&state=" + "y" * 12)   # хвост со следующей строки
    assert "user%3Aprofile+user" in d["url"]


def test_detect_gh_device_code():
    d = logins.detect(GH)
    assert d == {"kind": "gh", "service": "GitHub", "url": "https://github.com/login/device",
                 "code": "AB12-CD34", "wants": ""}


def test_detect_other_device_login():
    d = logins.detect(DEVICE)
    assert d["kind"] == "device" and d["code"] == "WXYZ-9876" and d["url"] == "https://example.invalid/devicelogin"
    assert d["service"] == "example.invalid"


def test_detect_mcp_login():
    d = logins.detect(MCP)
    assert d["kind"] == "mcp" and d["service"] == "notion" and d["wants"] == "url"
    assert d["url"].startswith("https://mcp.example.invalid/authorize?") and d["url"].endswith("localhost")


def test_plain_link_or_word_alone_is_not_a_login():
    assert logins.detect(ANSWER) is None                    # ссылка без слова входа («Claude Code» — не вход)
    assert logins.detect(["Please log in to continue", "❯ "]) is None   # слово без ссылки
    assert logins.detect([]) is None
    old = GH + [""] * logins.TAIL_LINES                     # запрос входа давно ушёл вверх — не показываем
    assert logins.detect(old) is None


def test_clean_code_one_line():
    assert logins.clean_code("  abc#DEF_123  ") == "abc#DEF_123"
    for bad in ("", "   ", "a\nb", "a\x1b[2~b", "x" * 513, None):
        with pytest.raises(ValueError):
            logins.clean_code(bad)
    assert logins.clean_code("x" * 512) == "x" * 512


class FakeTmux:
    def __init__(self):
        self.lines, self.pasted = list(CLAUDE), []
        self.w = {"@1": {"id": "@1", "path": "/srv/shop", "name": "shop", "cmd": "claude"},
                  "@2": {"id": "@2", "path": "/srv/demo", "name": "demo", "cmd": "claude", "space": "demo"}}

    def screen(self, wid, n=60):
        return self.lines

    def paste(self, wid, text):
        self.pasted.append((wid, text))
        return True

    def window(self, wid):
        return self.w.get(str(wid))

    def windows(self):
        return list(self.w.values())

    @contextlib.contextmanager
    def scope(self, slug):
        yield

    all_spaces = contextlib.nullcontext


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.add(2, "member")
    for uid in (1, 2):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    t = FakeTmux()
    monkeypatch.setattr(p, "tmux", t)
    monkeypatch.setattr(p, "window", lambda wid: t.window(wid))
    monkeypatch.setattr(p, "sessions", lambda pool=None, who=None: [{"id": "@1", "name": "shop"}])
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"p": p, "t": t, "base": f"http://127.0.0.1:{srv.server_address[1]}",
           "owner": p.auth.issue(1), "member": p.auth.issue(2)}
    srv.shutdown()


def call(base, path, body=None, token="", headers=None, cookie=""):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json",
                                  "Cookie": cookie or f"{webauth.COOKIE}={token}", **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_screen_login_owner_only(server):
    s = server
    code, d = call(s["base"], "/api/screen?w=@1", None, s["owner"])
    assert code == 200 and d["login"]["kind"] == "claude" and d["login"]["wants"] == "code"
    code, d = call(s["base"], "/api/screen?w=@1", None, s["member"])
    assert code == 200 and d["login"] is None                          # участнику — нет
    code, d = call(s["base"], "/api/screen?w=@2", None, s["owner"])
    assert code == 200 and d["login"] is None                          # окно пространства — нет
    s["t"].lines = ANSWER
    assert call(s["base"], "/api/screen?w=@1", None, s["owner"])[1]["login"] is None


def test_screen_login_not_in_focus(server):
    s = server
    code, d = call(s["base"], "/api/focus/new", {"w": "@1", "base": s["base"]}, s["owner"])
    assert code == 200, d
    token = d["url"].split("#focus=")[1]
    req = urllib.request.Request(s["base"] + "/api/focus/open", json.dumps({"token": token}).encode(),
                                 {"Content-Type": "application/json", focus.HEADER: "1"})
    with urllib.request.urlopen(req) as r:
        cookie = r.headers["Set-Cookie"].split(";")[0]
    fx = {focus.HEADER: "1"}
    code, d = call(s["base"], "/api/screen?w=@1", None, headers=fx, cookie=cookie)
    assert code == 200 and d["login"] is None and d["lines"]
    for path in ("/api/login/code", "/api/login/check"):
        code, d = call(s["base"], path, {"w": "@1", "code": "abc", "kind": "claude"}, headers=fx, cookie=cookie)
        assert code == 403 and d["code"] == "focus_scope", (path, code, d)
    assert s["t"].pasted == []


def test_login_code_to_window_one_line(server):
    s = server
    code, d = call(s["base"], "/api/login/code", {"w": "@1", "code": "  abc#DEF_123 "}, s["owner"])
    assert code == 200 and d["ok"] and s["t"].pasted == [("@1", "abc#DEF_123")]
    for bad in ("a\nb", "x" * 513, "", "a\x07b"):
        code, d = call(s["base"], "/api/login/code", {"w": "@1", "code": bad}, s["owner"])
        assert code == 400 and (not bad or bad not in d["error"]), (bad, code, d)   # код — не в тексте ошибки
    assert call(s["base"], "/api/login/code", {"w": "@1", "code": "abc"}, s["member"])[0] == 403
    code, d = call(s["base"], "/api/login/code", {"w": "@2", "code": "abc"}, s["owner"])        # окно пространства
    assert code == 400 and "пространства" in d["error"]
    assert s["t"].pasted == [("@1", "abc#DEF_123")]
    assert not {"/api/login/code", "/api/login/check"} & (webapp.FOCUS_POST | webapp.SPACE_OK)
    assert {"/api/login/code", "/api/login/check"} <= webapp.OWNER_ONLY


def test_login_check_by_kind(server, monkeypatch):
    s, p = server, server["p"]
    monkeypatch.setattr(webapp.setup, "auth", lambda exe, *a, **k: {"logged_in": True})
    code, d = call(s["base"], "/api/login/check", {"w": "@1", "kind": "claude"}, s["owner"])
    assert code == 200 and d["ok"] and d["login"] is None
    monkeypatch.setattr(webapp.setup, "auth", lambda exe, *a, **k: {"logged_in": None})
    code, d = call(s["base"], "/api/login/check", {"w": "@1", "kind": "claude"}, s["owner"])
    assert code == 200 and not d["ok"] and d["login"]["kind"] == "claude"
    # gh: код возврата «gh auth status»
    ran = []

    class R:
        returncode = 1
    monkeypatch.setattr(webapp.shutil, "which", lambda x: "/usr/bin/gh" if x == "gh" else None)
    monkeypatch.setattr(webapp.subprocess, "run", lambda args, **kw: ran.append(args) or R())
    s["t"].lines = GH
    code, d = call(s["base"], "/api/login/check", {"w": "@1", "kind": "gh"}, s["owner"])
    assert code == 200 and not d["ok"] and ran == [["/usr/bin/gh", "auth", "status"]]
    R.returncode = 0
    assert call(s["base"], "/api/login/check", {"w": "@1", "kind": "gh"}, s["owner"])[1]["ok"]
    # mcp: сервис из «Authenticating with …» в «claude mcp list» без ✔ — ещё не вошли
    s["t"].lines = MCP
    monkeypatch.setattr(p.mcp, "list", lambda fresh=False, home=None: [{"name": "notion", "ok": False}])
    assert not call(s["base"], "/api/login/check", {"w": "@1", "kind": "mcp"}, s["owner"])[1]["ok"]
    s["t"].lines = ANSWER
    monkeypatch.setattr(p.mcp, "list", lambda fresh=False, home=None: [{"name": "notion", "ok": True}])
    assert call(s["base"], "/api/login/check", {"w": "@1", "kind": "mcp"}, s["owner"])[1]["ok"]
    assert call(s["base"], "/api/login/check", {"w": "@1", "kind": "url"}, s["owner"])[1]["ok"]
    assert call(s["base"], "/api/login/check", {"w": "@1", "kind": "claude"}, s["member"])[0] == 403
