"""Мастер первого запуска: статус Claude Code, разбор экрана входа, код в окно, бот без Claude.

Живой tmux и настоящий claude не трогаем: subprocess, shutil.which и Tmux подменены."""

import json
import subprocess

import pytest

from gas_pult import bot, mcp, setup
from gas_pult.config import Config

URL1 = "https://claude.ai/oauth/authorize?code=true&client_id=00000000-0000-4000-8000-000000000000&response_ty"
URL2 = "pe=code&redirect_uri=https%3A%2F%2Fconsole.anthropic.com%2Foauth%2Fcode%2Fcallback&state=abc"
SCREEN = [" Claude Code can be used with your Claude subscription or billed based on API usage",
          " Browser didn't open? Use the url below to sign in (c to copy)",
          "",
          URL1,
          URL2,
          "",
          " Paste code here if prompted >"]


def fake_run(logged_in):
    def run(argv, **kw):
        if argv[1:] == ["--version"]:
            return subprocess.CompletedProcess(argv, 0, "2.1.316 (Claude Code)\n", "")
        if argv[1:3] == ["auth", "status"]:
            out = {"loggedIn": logged_in, "authMethod": "claude.ai" if logged_in else "none",
                   "apiProvider": "firstParty", "email": "x@example.com"}
            return subprocess.CompletedProcess(argv, 0 if logged_in else 1, json.dumps(out), "")
        raise AssertionError(argv)
    return run


@pytest.fixture
def cfgdir(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def test_parse_joins_wrapped_url_and_sees_code_prompt():
    r = setup.parse(SCREEN)
    assert r["url"] == URL1 + URL2
    assert r["code"] and not r["done"] and not r["error"]


def test_parse_short_lines_are_not_url_tail():
    r = setup.parse(["Visit: https://claude.ai/oauth/authorize?x=1", "Waiting...", "Paste code here >"])
    assert r["url"] == "https://claude.ai/oauth/authorize?x=1" and r["code"]


def test_parse_done_and_error():
    assert setup.parse(["Login successful. Press Enter to continue"])["done"]
    assert not setup.parse(["Not logged in"])["done"]
    assert setup.parse(["OAuth error: Invalid code"])["error"] == "OAuth error: Invalid code"


def test_status_without_claude(monkeypatch, cfgdir):
    monkeypatch.setattr(setup.shutil, "which", lambda x: None)
    st = setup.status()
    assert not st["ready"] and not st["claude"]["installed"]
    assert any(not c["ok"] and "Claude Code" in c["name"] for c in st["checks"])
    assert "❌" in setup.text(st)


def test_status_not_logged_in_and_logged_in(monkeypatch, cfgdir):
    monkeypatch.setattr(setup.shutil, "which", lambda x: "/bin/" + x)
    monkeypatch.setattr(setup.subprocess, "run", fake_run(False))
    st = setup.status()
    assert st["claude"]["installed"] and st["claude"]["version"].startswith("2.1")
    assert not st["ready"] and st["auth"]["logged_in"] is False
    monkeypatch.setattr(setup.subprocess, "run", fake_run(True))
    st = setup.status()
    assert st["ready"] and st["auth"]["method"] == "claude.ai"
    assert "email" not in json.dumps(st)                     # почту наружу не отдаём


def test_auth_passes_config_dir(monkeypatch, tmp_path):
    seen = {}

    def run(argv, env=None, **kw):
        seen["env"] = env
        return subprocess.CompletedProcess(argv, 0, json.dumps({"loggedIn": True}), "")
    monkeypatch.setattr(setup.subprocess, "run", run)
    setup.auth("claude", config_dir=tmp_path / "anna")
    assert seen["env"]["CLAUDE_CONFIG_DIR"] == str(tmp_path / "anna")


def test_auth_old_claude_falls_back_to_credentials_file(monkeypatch, tmp_path):
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "unknown", ""))
    for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    assert setup.auth("claude", config_dir=tmp_path)["logged_in"] is None
    (tmp_path / ".credentials.json").write_text("{}")
    assert setup.auth("claude", config_dir=tmp_path)["logged_in"] is True


class FakeTmux:
    def __init__(self, screen):
        self.wins, self.scr, self.pasted, self.killed, self.cmds = [], screen, [], [], []

    def windows(self):
        return self.wins

    def new_window(self, name, path, command, mark="claude"):
        self.cmds.append(command)
        self.wins.append({"id": "@9", "name": name, "cmd": "claude", "mark": mark, "path": path})
        return "@9"

    def screen(self, wid, n=25):
        return list(self.scr)

    def paste(self, wid, text):
        self.pasted.append((wid, text))

    def kill(self, wid):
        self.killed.append(wid)
        self.wins = [w for w in self.wins if w["id"] != wid]


def test_login_flow(monkeypatch):
    monkeypatch.setattr(setup.shutil, "which", lambda x: "/bin/" + x)
    monkeypatch.setattr(setup.time, "sleep", lambda s: None)
    t = FakeTmux(SCREEN)
    lg = setup.Login("main", tmux=t, home="/home/u")
    st = lg.start()
    assert st["url"] == URL1 + URL2 and st["code"]
    assert t.cmds == ["claude auth login"]
    assert t.wins[0]["mark"] == "login"                      # не «claude»: окно входа — не сессия
    assert lg.start()["url"] and len(t.cmds) == 1             # второй раз — то же окно

    with pytest.raises(ValueError):
        lg.send_code("код с пробелом\nи строкой")
    monkeypatch.setattr(setup.subprocess, "run", fake_run(True))
    t.scr = ["Login successful. Press Enter to continue"]
    r = lg.send_code("  abcDEF123#xyz_456  ")
    assert t.pasted == [("@9", "abcDEF123#xyz_456")]         # код ушёл в окно входа, без пробелов
    assert r["ok"] and t.killed == ["@9"]                      # вход подтвердился — окно закрыто


def test_login_failed_code_keeps_window(monkeypatch):
    monkeypatch.setattr(setup.shutil, "which", lambda x: "/bin/" + x)
    monkeypatch.setattr(setup.time, "sleep", lambda s: None)
    monkeypatch.setattr(setup.subprocess, "run", fake_run(False))
    t = FakeTmux(SCREEN)
    lg = setup.Login("main", tmux=t)
    lg.start()
    t.scr = [*SCREEN, "OAuth error: Invalid code"]
    r = lg.send_code("abcd1234")
    assert not r["ok"] and "Invalid code" in r["error"] and not t.killed


def test_login_without_window_or_claude(monkeypatch):
    t = FakeTmux(SCREEN)
    monkeypatch.setattr(setup.shutil, "which", lambda x: "/bin/" + x)
    with pytest.raises(LookupError):
        setup.Login("main", tmux=t).send_code("abcd1234")
    monkeypatch.setattr(setup.shutil, "which", lambda x: None)
    with pytest.raises(RuntimeError, match="не установлен"):
        setup.Login("main", tmux=t).start()


def test_login_command_with_config_dir():
    lg = setup.Login("main", claude="claude --verbose", config_dir="/srv/people/anna claude", tmux=FakeTmux([]))
    assert lg.command() == "env CLAUDE_CONFIG_DIR='/srv/people/anna claude' claude auth login"
    with pytest.raises(ValueError):
        setup.Login("main", env={"A;rm": "x"}, tmux=FakeTmux([])).command()


def test_mcp_without_claude(monkeypatch):
    def nope(*a, **k):
        raise FileNotFoundError("claude")
    monkeypatch.setattr(mcp.subprocess, "run", nope)
    assert mcp.Mcp().list(fresh=True) == []


# ---------- бот без Claude ----------
def make_bot(monkeypatch, cfgdir):
    monkeypatch.setattr(setup.shutil, "which", lambda x: None)           # Claude Code не установлен
    sent = []

    class FakeApi:
        def __init__(self, token):
            pass

        def __call__(self, method, **kw):
            if method == "getMe":
                return {"username": "test_bot"}
            if method == "getChatMenuButton":
                return {"type": "web_app", "web_app": {"url": "https://pult.example.com/"}}
            if method == "getUpdates":
                raise KeyboardInterrupt                       # выйти из вечного цикла опроса
            sent.append((method, kw))
            return {"message_id": len(sent)}

        def redact(self, e):
            return str(e)
    monkeypatch.setattr(bot, "Api", FakeApi)
    p = bot.Pult(Config(token="1:T", owners=[1]))
    return p, sent


def test_bot_starts_without_claude(monkeypatch, cfgdir, capsys):
    p, _ = make_bot(monkeypatch, cfgdir)
    monkeypatch.setattr(bot.threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: None})())
    with pytest.raises(KeyboardInterrupt):
        p.run()                                               # старт не падает до опроса Telegram
    assert "не установлен" in capsys.readouterr().out


def test_start_shows_wizard(monkeypatch, cfgdir):
    p, sent = make_bot(monkeypatch, cfgdir)
    p.on_message({"chat": {"id": 1}, "from": {"id": 1}, "text": "/start", "message_id": 5})
    text, kw = sent[-1][1]["text"], sent[-1][1]["reply_markup"]
    assert "не установлен" in text
    flat = [b for row in kw["inline_keyboard"] for b in row]
    names = [b["text"] for b in flat]
    assert any("интеграции" in n for n in names) and any("Ключ" in n for n in names)
    assert any("Проверка" in n for n in names)
    assert not any("Войти" in n for n in names)               # без Claude Code входить нечем
    assert any(b.get("web_app", {}).get("url", "").endswith("?view=integrations") for b in flat)
    assert any(b.get("url") == setup.DOC_URL for b in flat)


def test_bot_code_goes_to_login_window(monkeypatch, cfgdir):
    p, sent = make_bot(monkeypatch, cfgdir)
    got = []
    p.login.send_code = lambda code: got.append(code) or {"ok": True, "lines": []}
    p.waiting[1] = "code"
    p.on_message({"chat": {"id": 1}, "from": {"id": 1}, "text": "abc#123", "message_id": 6})
    assert got == ["abc#123"] and "выполнен" in sent[-1][1]["text"]


def test_bot_login_sends_link(monkeypatch, cfgdir):
    p, sent = make_bot(monkeypatch, cfgdir)
    p.login.start = lambda: {"url": URL1 + URL2, "code": True, "done": False, "lines": []}
    p.on_setup(1, "login")
    assert URL1 + URL2 in sent[-1][1]["text"] and p.waiting[1] == "code"


def test_panel_setup_owner_only_and_no_session_without_claude(monkeypatch, cfgdir):
    from gas_pult import webapp
    assert {"/api/setup/status", "/api/setup/login", "/api/setup/code"} <= webapp.OWNER_ONLY
    monkeypatch.setattr(setup.shutil, "which", lambda x: None)
    panel = webapp.Panel(Config(token="1:T", owners=[1]))
    st = panel.setup_status()
    assert not st["ready"] and st["login"] is None
    with pytest.raises(ValueError, match="не установлен"):
        panel.new(0)
