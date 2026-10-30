from pathlib import Path

import pytest

from gas_pult import webapp
from gas_pult.config import Config


@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    cmds = [{"i": 0, "cmd": "ls", "kind": "local", "danger": False, "sha": "aaa"},
            {"i": 1, "cmd": "rm -rf build", "kind": "local", "danger": True, "sha": "bbb"},
            {"i": 2, "cmd": "brew install x", "kind": "foreign", "danger": False, "sha": "ccc"}]
    monkeypatch.setattr(p, "commands", lambda w: cmds)
    monkeypatch.setattr(webapp, "execute", lambda cmd, cwd: (0, 0.1, f"ran {cmd}"))
    return p


W = {"id": "@1", "path": "/tmp"}


def test_run_ok(panel):
    assert panel.run(W, 0, "aaa", False) == {"code": 0, "seconds": 0, "out": "ran ls", "cut": False}


def test_run_rejects_changed_answer(panel):
    with pytest.raises(ValueError, match="изменился"):
        panel.run(W, 0, "zzz", False)          # отпечаток не совпал — браузер не подсунет свою команду


def test_run_danger_needs_confirm(panel):
    assert panel.run(W, 1, "bbb", False) == {"confirm": True}
    assert panel.run(W, 1, "bbb", True)["out"] == "ran rm -rf build"


def test_run_foreign_refused(panel):
    with pytest.raises(ValueError, match="вручную"):
        panel.run(W, 2, "ccc", True)


def test_upload_sanitizes_name(panel, tmp_path):
    p = panel.upload("..%2F..%2Fetc%2Fpasswd фото.jpg", b"x")
    assert p.startswith(str(tmp_path / "inbox")) and "/etc/" not in p.split("inbox")[1]
    assert Path(p).read_bytes() == b"x"


def test_find_auth_joins_wrapped_url():
    from gas_pult.webapp import find_auth
    lines = ["   Authenticating with notion…",
             "   If your browser doesn't open automatically, copy this URL manually (c to copy)",
             "   https://mcp.notion.com/authorize?response_type=code&client_id=x&code_challe",
             "   nge_method=S256&redirect_uri=http%3A%2F%2Flocalhost%3A49442%2Fcallback&state=abc",
             "   If the redirect page shows a connection error, paste the URL from your browser's address bar:",
             "   URL >"]
    a = find_auth(lines)
    assert a["service"] == "notion" and a["paste"]
    assert a["url"].endswith("callback&state=abc") and "code_challenge_method=S256" in a["url"]
    assert find_auth(["❯ ", "просто экран"]) is None


def test_key_allows_ctrl_c_only_from_list(panel, monkeypatch):
    sent = []
    monkeypatch.setattr(panel.tmux, "keys", lambda wid, k: sent.append(k))
    monkeypatch.setattr(panel.tmux, "screen", lambda wid, n: ["ok"])
    monkeypatch.setattr(webapp.time, "sleep", lambda s: None)
    assert panel.key(W, "C-c") == ["ok"] and sent == ["C-c"]
    with pytest.raises(ValueError):
        panel.key(W, "C-d")


def test_preview_cached_by_revision(panel, monkeypatch):
    calls = []
    monkeypatch.setattr(webapp.transcripts, "preview", lambda path: calls.append(path) or "строка")
    assert panel.preview("/p", "r1") == "строка" and panel.preview("/p", "r1") == "строка"
    panel.preview("/p", "r2")
    assert calls == ["/p", "/p"]


def test_new_reuses_window_in_same_folder(panel, monkeypatch):
    monkeypatch.setattr(panel.pult, "projects", lambda: ["/p/a", "/p/b"])
    monkeypatch.setattr(panel.pult, "project_window",
                        lambda path: {"id": "@7", "name": "a-0900"} if path == "/p/a" else None)
    monkeypatch.setattr(panel.tmux, "new_window", lambda name, path, cmd, **kw: "@9")
    monkeypatch.setattr(panel.pult, "set_state", lambda **kw: None)
    assert panel.new(0) == {"id": "@7", "existing": "a-0900"}
    assert panel.new(1) == {"id": "@9"}


def test_new_session_in_profile_and_restart(panel, monkeypatch):
    opened = []
    monkeypatch.setattr(panel.pult, "projects", lambda: ["/p/a"])
    monkeypatch.setattr(panel.pult, "project_window", lambda path: None)
    monkeypatch.setattr(panel.pult, "set_state", lambda **kw: None)
    monkeypatch.setattr(panel.tmux, "new_window",
                        lambda name, path, cmd, **kw: opened.append((name, path, cmd)) or "@9")
    monkeypatch.setattr(webapp.models, "command", lambda base, profile, st: f"{base} [{profile or 'claude'}]")
    assert panel.new(0, "zai") == {"id": "@9"} and opened[-1][2] == "claude [zai]"
    monkeypatch.setattr(panel, "close", lambda w: "Claude не вышел (возможно, занят) — посмотрите экран")
    with pytest.raises(ValueError, match="не вышел"):
        panel.restart({"id": "@1", "name": "a-0900", "path": "/p/a"}, "deepseek")
    monkeypatch.setattr(panel, "close", lambda w: "закрыто")
    assert panel.restart({"id": "@1", "name": "a-0900", "path": "/p/a"}, "deepseek") == {"id": "@9"}
    assert opened[-1] == ("a-0900", "/p/a", "claude [deepseek] --continue")      # по умолчанию разговор продолжается
    panel.restart({"id": "@1", "name": "a-0900", "path": "/p/a"}, "zai", keep=False)
    assert opened[-1][2] == "claude [zai]"


def test_model_key_saved_without_voice_reset(panel, monkeypatch):
    saved, state = {}, {}
    monkeypatch.setattr(webapp.providers, "check_model_key", lambda p, k: True)
    monkeypatch.setattr(webapp.providers, "save_key", lambda p, k: saved.__setitem__(p, k))
    monkeypatch.setattr(panel.pult, "set_state", lambda **kw: state.update(kw))
    assert panel.set_key("deepseek", " sk-0123456789abcdef ") == {"checked": True}
    assert saved == {"deepseek": "sk-0123456789abcdef"}
    with pytest.raises(ValueError, match="не похоже"):
        panel.set_key("zai", "short")
    panel.remove_key("deepseek")
    assert "tts_provider" not in state                     # голос не сбрасывается из-за ключа модели


def test_effort_only_known_levels(panel, monkeypatch):
    sent = []
    monkeypatch.setattr(panel, "slash", lambda w, cmd: sent.append(cmd) or ["ok"])
    assert panel.effort(W, "xhigh") == ["ok"] and sent == ["/effort xhigh"]
    with pytest.raises(ValueError):
        panel.effort(W, "xhigh; rm -rf /")


def test_service_worker_served_from_root(panel):
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/sw.js")
        assert r.headers["Content-Type"].startswith("text/javascript") and b"notificationclick" in r.read()
    finally:
        srv.shutdown()


def test_stopped_session_listed_and_revived(panel, monkeypatch):
    stopped = {"id": "@3", "name": "shop", "path": "/tmp", "cmd": "zsh", "mark": "zai", "stopped": True,
               "channel": False, "profile": ""}
    monkeypatch.setattr(panel.tmux, "windows", lambda: [stopped])
    monkeypatch.setattr(panel.tmux, "window", lambda wid: stopped if wid == "@3" else None)
    s = panel.sessions()
    assert s[0]["status"] == "stopped" and s[0]["profile"] == "zai"
    calls = []
    monkeypatch.setattr(webapp.models, "command", lambda base, profile, st: f"claude [{profile}]")
    monkeypatch.setattr(panel.tmux, "respawn", lambda wid, path, cmd, mark: calls.append((wid, cmd, mark)))
    monkeypatch.setattr(panel.pult, "set_state", lambda **kw: None)
    assert panel.revive("@3") == {"id": "@3"}
    assert calls == [("@3", "claude [zai] --continue", "zai")]     # тот же поставщик, разговор продолжается
    with pytest.raises(ValueError):
        panel.revive("@9")
