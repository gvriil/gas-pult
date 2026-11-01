"""Своя папка Claude Code у каждого человека пульта: окна, MCP, журналы (docs/adr/0001-claude-config-per-person.md).

Живой tmux и настоящий claude не запускаются: subprocess и методы подменены."""

import json
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import mcp, models, people, tmux, transcripts, webapp, webauth
from gas_pult.config import Config

OWNER, MEMBER, VIEWER = 1001, 1002, 1003


def call(base, path, body=None, token=""):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r), ""
    except urllib.error.HTTPError as e:
        return e.code, json.load(e), ""


def test_claude_dir_owner_untouched_member_private(tmp_path):
    assert people.claude_dir(tmp_path, OWNER, [OWNER]) is None          # владелец — ~/.claude, как раньше
    assert people.claude_dir(tmp_path, webauth.LEGACY, [OWNER]) is None  # вход кодом владельцу
    assert people.claude_dir(tmp_path, "x", [OWNER]) is None
    d = people.claude_dir(tmp_path, MEMBER, [OWNER])
    assert d == tmp_path / "people" / str(MEMBER) / "claude" and d.is_dir()
    assert all(x.stat().st_mode & 0o777 == 0o700 for x in (d, d.parent, d.parent.parent))
    assert people.home_of({"by": str(MEMBER)}, tmp_path) == d
    assert people.home_of({"by": ""}, tmp_path) is None and people.home_of({}, tmp_path) is None   # окно владельца


def test_command_gets_config_dir_prefix(tmp_path, monkeypatch):
    home = tmp_path / "a b" / "claude"
    assert models.command("claude", "", {}) == "claude"
    assert models.command("claude", "claude", {}, home=home) == f"CLAUDE_CONFIG_DIR='{home}' claude"
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(models.providers, "load_keys", lambda: {"zai": "k" * 20})
    cmd = models.command("claude", "zai", {}, home=home)
    assert cmd.startswith(f"CLAUDE_CONFIG_DIR='{home}' claude --settings ") and models.profile_of(cmd.split()[1:])


def test_new_window_marks_person(monkeypatch):
    runs, sets = [], []
    monkeypatch.setattr(tmux.subprocess, "run",
                        lambda args, **kw: runs.append(args) or subprocess.CompletedProcess(args, 0, "@5\n", ""))
    t = tmux.Tmux("main", socket="/nonexistent/s")
    monkeypatch.setattr(t, "run", lambda *a, **kw: sets.append(a) or "")
    assert t.new_window("w", "/p", "claude", by=str(MEMBER)) == "@5"
    assert ("set-option", "-w", "-t", "@5", "@gas_pult_by", str(MEMBER)) in sets
    sets.clear()
    t.new_window("w", "/p", "claude")
    assert not any("@gas_pult_by" in a for a in sets)                   # окно владельца — без отметки


def test_mcp_runs_with_person_dir(tmp_path, monkeypatch):
    seen = []
    def run(args, **kw):
        env = kw.get("env")
        seen.append(env and env.get("CLAUDE_CONFIG_DIR"))
        name = "mine" if env else "owner"
        return subprocess.CompletedProcess(args, 0, f"{name}: https://x/mcp (HTTP) - ✔ Connected\n", "")
    monkeypatch.setattr(mcp.subprocess, "run", run)
    m, home = mcp.Mcp(), tmp_path / "claude"
    assert [s["name"] for s in m.list()] == ["owner"]
    assert [s["name"] for s in m.list(home=home)] == ["mine"]           # кеш — у каждого свой
    assert [s["name"] for s in m.list()] == ["owner"] and seen == [None, str(home)]
    m.add("context7", "ctx", {}, home=home)
    assert seen[-2:] == [str(home), str(home)]                          # add-json и свежий список — в папке человека


def test_transcripts_from_person_dir(tmp_path):
    home, path = tmp_path / "claude", "/srv/proj"
    d = home / "projects" / "-srv-proj"
    d.mkdir(parents=True)
    rows = [{"type": "user", "message": {"content": "привет"}},
            {"type": "assistant",
             "message": {"content": [{"type": "text", "text": "ответ"}], "stop_reason": "end_turn"}}]
    (d / "s.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    assert transcripts.last_answer(path, home) == "ответ" and transcripts.revision(path, home)
    assert [m["text"] for m in transcripts.history(path, home=home)[0]] == ["привет", "ответ"]
    assert transcripts.preview(path, home=home) == "ответ"
    assert transcripts.project_dir(path) == transcripts.CLAUDE_PROJECTS / "-srv-proj"   # без папки — как раньше


@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    p = webapp.Panel(Config(token="1:T", owners=[OWNER]))
    p.people.add(MEMBER, "member")
    p.people.add(VIEWER, "viewer")
    monkeypatch.setattr(p.pult, "set_state", lambda **kw: None)
    monkeypatch.setattr(p.pult, "projects", lambda: ["/p/a"])
    monkeypatch.setattr(p.pult, "project_window", lambda path: None)
    return p


def test_new_restart_revive_keep_who_opened(panel, monkeypatch, tmp_path):
    opened, respawned = [], []
    monkeypatch.setattr(panel.tmux, "new_window", lambda name, path, cmd, mark="claude", by="":
                        opened.append((cmd, by)) or "@9")
    home = tmp_path / "people" / str(MEMBER) / "claude"
    panel.new(0, "", person=MEMBER)
    assert opened[-1] == (f"CLAUDE_CONFIG_DIR={home} claude", str(MEMBER)) and home.is_dir()
    panel.new(0, "")
    assert opened[-1] == ("claude", "")                                 # владелец — как раньше
    monkeypatch.setattr(panel, "close", lambda w: "закрыто")
    panel.restart({"id": "@1", "name": "a", "path": "/p/a", "by": str(MEMBER)}, "")   # нажал владелец — папка участника
    assert opened[-1] == (f"CLAUDE_CONFIG_DIR={home} claude --continue", str(MEMBER))
    w = {"id": "@3", "name": "a", "path": "/p/a", "mark": "claude", "stopped": True, "by": str(MEMBER)}
    monkeypatch.setattr(panel.tmux, "window", lambda wid: w)
    monkeypatch.setattr(panel.tmux, "respawn", lambda wid, path, cmd, mark: respawned.append(cmd))
    panel.revive("@3")
    assert respawned == [f"CLAUDE_CONFIG_DIR={home} claude --continue"]


def test_mcp_login_only_in_own_window(panel, monkeypatch, tmp_path):
    home = panel.pult.claude_dir(MEMBER)
    wins = [{"id": "@1", "by": ""}, {"id": "@2", "by": str(MEMBER)}]
    monkeypatch.setattr(panel.tmux, "windows", lambda: wins)
    monkeypatch.setattr(panel, "sessions", lambda: [{"id": "@1", "status": "idle", "active": True},
                                                    {"id": "@2", "status": "idle", "active": False}])
    monkeypatch.setattr(panel, "window", lambda wid: {"id": wid})
    assert panel.login_window(home)["id"] == "@2" and panel.login_window()["id"] == "@1"
    with pytest.raises(ValueError, match="вашей"):
        panel.login_window(tmp_path / "people" / "1004" / "claude")
    with pytest.raises(ValueError, match="другого человека"):
        panel.mcp_finish({"id": "@1", "by": ""}, "http://localhost:1/callback?code=x", "n", home)


@pytest.fixture
def server(panel, monkeypatch):
    calls = []
    monkeypatch.setattr(panel.mcp, "list", lambda fresh=False, home=None: calls.append(("list", home)) or [])
    monkeypatch.setattr(panel.mcp, "add", lambda preset, name, values, home=None: calls.append(("add", home)) or "ok")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, f"http://127.0.0.1:{srv.server_address[1]}", calls
    srv.shutdown()


def test_api_mcp_is_per_person(server, tmp_path):
    panel, base, calls = server
    owner, member, viewer = (panel.auth.issue(u) for u in (OWNER, MEMBER, VIEWER))
    home = tmp_path / "people" / str(MEMBER) / "claude"
    code, d, _ = call(base, "/api/mcp", None, member)
    assert code == 200 and d["personal"] and "stdio" not in {p["id"] for p in d["presets"]}
    assert calls[-1] == ("list", home)
    code, d, _ = call(base, "/api/mcp", None, owner)
    assert code == 200 and not d["personal"] and "stdio" in {p["id"] for p in d["presets"]}
    assert calls[-1] == ("list", None)
    assert call(base, "/api/mcp", None, viewer)[0] == 403                # наблюдателю интеграций нет
    assert call(base, "/api/mcp/add", {"preset": "stdio", "name": "x1"}, member)[0] == 400
    assert call(base, "/api/mcp/add", {"preset": "context7", "name": "ctx"}, member)[0] == 200
    assert calls[-1] == ("add", home)
    assert call(base, "/api/models", {"profile": "zai"}, member)[0] == 403   # модели и ключи — по-прежнему владельцу
