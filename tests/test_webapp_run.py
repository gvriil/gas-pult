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
