"""Репозитории GitHub в живой сессии (задача 43, repos.py).

Без сети и без живого tmux: git — поддельная программа во временной папке, оболочка пространства — ``sh -c`` здесь же
(вместо ``sudo -u … tmux run-shell``), окна — заглушки. Токены — заведомо поддельные, собраны склейкой строк.
"""

import base64
import contextlib
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import focus, repos, space_sessions, tenants, webapp, webauth
from gas_pult.config import Config

FAKE = "github" + "_pat_" + "A1b2C3d4" * 4          # поддельный токен: сканер секретов его не примет за настоящий

FAKE_GIT = r"""#!/bin/sh
printf '%s\n' "$*" >> "$GP_LOG"
printf '%s\n' "${GIT_CONFIG_KEY_0:-}=${GIT_CONFIG_VALUE_0:-}" >> "$GP_ENVLOG"
if [ "$1" = clone ]; then
  mkdir -p "$5/.git"; printf '[remote "origin"]\n\turl = %s\n' "$4" > "$5/.git/config"
fi
if [ "$1" = -C ] && [ "$3" = remote ]; then sed -n 's/.*url = //p' "$2/.git/config"; fi
exit 0
"""


# ---------- разбор ссылки и список в state.json ----------
def test_parse_links():
    for src in ("https://github.com/acme/Shop.git", "github.com/acme/Shop", "git@github.com:acme/Shop.git",
                "acme/Shop", "https://github.com/acme/Shop/", "https://github.com/acme/Shop?tab=readme"):
        assert repos.parse(src) == ("acme/Shop", "Shop"), src
    for bad in ("", "https://gitlab.com/a/b", "acme/../x", "acme/.hidden", "a/b c", "https://github.com/a",
                "ac me/x", "acme/x; rm -rf /"):
        with pytest.raises(ValueError):
            repos.parse(bad)


def test_state_add_remove_and_flags():
    st: dict = {}
    st[repos.STATE] = repos.added(st, "/p/a", "/p/x")
    st[repos.STATE] = repos.added(st, "/p/a", "/p/x")                     # повтор — без дубля
    st[repos.STATE] = repos.added(st, "/p/a", "/p/y z")
    assert repos.of(st, "/p/a") == ["/p/x", "/p/y z"]
    assert repos.flags(st, "/p/a") == " --add-dir /p/x --add-dir '/p/y z'"
    assert repos.flags(st, "/p/other") == ""
    st[repos.STATE] = repos.removed(st, "/p/a", "/p/x")
    assert repos.of(st, "/p/a") == ["/p/y z"]
    st[repos.STATE] = repos.removed(st, "/p/a", "/p/y z")
    assert st[repos.STATE] == {}


# ---------- владелец: clone / pull ----------
class Runner:
    def __init__(self, origin="https://github.com/acme/shop.git", code=0):
        self.calls, self.origin, self.code = [], origin, code

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw.get("env") or {}))
        out = self.origin if "get-url" in argv else ""
        if argv[1] == "clone":
            Path(argv[-1], ".git").mkdir(parents=True)
        return subprocess.CompletedProcess(argv, self.code, out, "")


def test_owner_clone_then_pull(tmp_path):
    root = tmp_path / "projects"
    run = Runner()
    path, act = repos.owner_fetch("acme/shop", root, run)
    assert (path, act) == (str(root / "shop"), "clone")
    argv, env = run.calls[-1]
    assert argv == ["git", "clone", "-q", "--", "https://github.com/acme/shop.git", str(root / "shop")]
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    path, act = repos.owner_fetch("https://github.com/acme/shop", root, run)   # папка уже есть — pull
    assert act == "pull" and run.calls[-1][0] == ["git", "-C", str(root / "shop"), "pull", "--ff-only", "-q"]
    assert not any(a == "clone" for argv, _ in run.calls[2:] for a in argv)


def test_owner_refuses_foreign_folder(tmp_path):
    root = tmp_path / "projects"
    (root / "shop").mkdir(parents=True)
    with pytest.raises(ValueError, match="не репозиторий"):
        repos.owner_fetch("acme/shop", root, Runner())
    (root / "shop" / ".git").mkdir()
    with pytest.raises(ValueError, match="другой репозиторий"):
        repos.owner_fetch("acme/shop", root, Runner(origin="https://github.com/other/shop.git"))


def test_owner_error_is_plain_and_without_token(tmp_path):
    class Bad(Runner):
        def __call__(self, argv, **kw):
            return subprocess.CompletedProcess(argv, 128, "", f"fatal: Authentication failed {FAKE}")
    with pytest.raises(RuntimeError) as e:
        repos.owner_fetch("acme/shop", tmp_path, Bad())
    assert FAKE not in str(e.value) and "GitHub не пустил" in str(e.value)


def test_owner_list_from_gh():
    data = [{"full_name": "acme/shop", "private": True, "description": "магазин"}, {"x": 1}]

    def run(argv, **kw):
        assert argv[:2] == ["gh", "api"]
        return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")
    assert repos.owner_list(run) == [{"full": "acme/shop", "private": True, "about": "магазин"}]

    def missing(argv, **kw):
        raise FileNotFoundError
    with pytest.raises(RuntimeError, match="ссылку"):
        repos.owner_list(missing)


# ---------- пространство: токен — только внутри, через окружение ----------
@pytest.fixture
def space(tmp_path, monkeypatch):
    root = tmp_path / "srv"
    monkeypatch.setenv("GAS_PULT_TENANTS_ROOT", str(root))
    p = tenants.paths("demo")
    p["claude"].mkdir(parents=True)
    p["home"].mkdir(parents=True)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "git").write_text(FAKE_GIT)
    (bin_ / "git").chmod(0o755)
    log, envlog = tmp_path / "argv.log", tmp_path / "env.log"
    log.touch()
    envlog.touch()
    scripts = []

    def sh(slug, script, timeout=30):
        """Как space_sessions.sh, но здесь: ``sh -c`` с поддельным git первым в PATH."""
        assert slug == "demo"
        scripts.append(script)
        env = {"PATH": f"{bin_}:{os.path.dirname(sys.executable)}:/usr/bin:/bin", "GP_LOG": str(log),
               "GP_ENVLOG": str(envlog), "HOME": str(p["home"])}
        r = subprocess.run(["sh", "-c", script + " 2>&1"], capture_output=True, text=True, env=env, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(r.stdout.strip() or "не вышло")
        return r.stdout
    return {"p": p, "sh": sh, "log": log, "envlog": envlog, "scripts": scripts}


def test_space_clone_token_never_in_argv_url_or_config(space):
    space["p"]["secrets"].write_text(json.dumps({"openrouter": "x", "github": FAKE}))
    path, act = repos.space_fetch("demo", "acme/shop", space["sh"])
    dest = space["p"]["home"] / "projects" / "shop"
    assert (path, act) == (str(dest), "clone")
    script = space["scripts"][-1]
    assert FAKE not in script and "#" not in script         # в команде tmux — ни токена, ни форматов tmux «#{…}»
    argv = space["log"].read_text()
    assert FAKE not in argv and "clone -q -- https://github.com/acme/shop.git " + str(dest) in argv
    cfg = (dest / ".git" / "config").read_text()
    assert FAKE not in cfg and "url = https://github.com/acme/shop.git" in cfg     # адрес remote — без токена
    basic = base64.b64encode(f"x-access-token:{FAKE}".encode()).decode()
    assert f"http.https://github.com/.extraheader=Authorization: Basic {basic}" in space["envlog"].read_text()
    path, act = repos.space_fetch("demo", "https://github.com/acme/shop", space["sh"])   # уже есть — pull
    assert act == "pull" and "pull --ff-only -q" in space["log"].read_text()
    assert FAKE not in space["log"].read_text()


def test_space_token_from_github_integration(space):
    """Нет ключа в secrets.json — токен из интеграции GitHub Claude Code пространства (заголовок Bearer)."""
    (space["p"]["claude"] / ".claude.json").write_text(json.dumps({"mcpServers": {
        "linear": {"url": "https://mcp.linear.app/mcp", "headers": {"Authorization": "Bearer lin"}},
        "github": {"type": "http", "url": "https://api.githubcopilot.com/mcp/",
                   "headers": {"Authorization": "Bearer " + FAKE}}}}))
    repos.space_fetch("demo", "acme/shop", space["sh"])
    basic = base64.b64encode(f"x-access-token:{FAKE}".encode()).decode()
    assert basic in space["envlog"].read_text() and FAKE not in space["log"].read_text()


def test_space_without_token_public_clone_and_hint(space):
    repos.space_fetch("demo", "acme/open", space["sh"])                    # открытый — можно и без токена
    assert space["envlog"].read_text().strip() == "="                       # заголовка нет
    with pytest.raises(repos.NoToken) as e:                                 # список — без токена нечем
        repos.space_list("demo", space["sh"])
    h = e.value.hint
    assert h["url"] == repos.TOKEN_URL and "pult-tenant key demo github" in " ".join(h["steps"])
    assert "fine-grained" in " ".join(h["steps"])


def test_space_auth_failure_gives_hint(monkeypatch):
    def sh(slug, script, timeout=30):
        raise RuntimeError("fatal: could not read Username for 'https://github.com': terminal prompts disabled")
    with pytest.raises(repos.NoToken):
        repos.space_fetch("demo", "acme/private", sh)


def test_space_list_parses_output(monkeypatch):
    rows = [{"full_name": "acme/a", "private": False, "description": None}]
    got = repos.space_list("demo", lambda slug, script, timeout=30: "шум\n" + json.dumps(rows) + "\n")
    assert got == [{"full": "acme/a", "private": False, "about": ""}]


# ---------- панель: /add-dir, перезапуск, «Продолжить», «Отключить» ----------
@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    p = webapp.Panel(Config(token="1:T", owners=[1], models=["opus"]))
    state: dict = {}
    monkeypatch.setattr(p.pult, "state", lambda: json.loads(json.dumps(state)))
    monkeypatch.setattr(p.pult, "set_state", lambda **kw: state.update(kw))
    monkeypatch.setattr(p.pult, "module_root", lambda: tmp_path / "projects")
    opened, sent, fetched = [], [], []
    monkeypatch.setattr(p.tmux, "new_window", lambda name, path, cmd, **kw: opened.append(cmd) or "@9")
    monkeypatch.setattr(p, "close", lambda w: "закрыто")
    monkeypatch.setattr(p, "slash", lambda w, cmd: sent.append((w["id"], cmd)) or ["Added"])
    monkeypatch.setattr(webapp.models, "command", lambda base, profile, st, **kw: "claude")

    def fetch(full, root):
        d = Path(root) / repos.parse(full)[1]
        d.mkdir(parents=True, exist_ok=True)
        fetched.append(full)
        return str(d), "clone"
    monkeypatch.setattr(repos, "owner_fetch", fetch)
    p.t = {"state": state, "opened": opened, "sent": sent, "fetched": fetched, "root": tmp_path / "projects"}
    return p


def test_add_sends_add_dir_and_restart_passes_it(panel):
    w = {"id": "@1", "name": "a", "path": "/p/a", "profile": "claude", "cmd": "claude"}
    d = panel.repo_add(w, "https://github.com/acme/shop")
    path = str(panel.t["root"] / "shop")
    assert d["path"] == path and d["action"] == "clone" and d["sent"] is True
    assert panel.t["sent"] == [("@1", f"/add-dir {path}")]
    assert d["added"] == [{"path": path, "name": "shop"}]
    panel.restart(w, "claude")
    assert panel.t["opened"][-1] == f"claude --add-dir {path} --continue"


def test_revive_passes_add_dir(panel, monkeypatch):
    panel.t["state"][repos.STATE] = {"/p/c": ["/r/one", "/r/two"]}
    respawned = []
    win = {"stopped": True, "mark": "claude", "path": "/p/c"}
    monkeypatch.setattr(panel.tmux, "window", lambda wid: {"id": wid, **win})
    monkeypatch.setattr(panel.tmux, "respawn", lambda wid, path, cmd, mark="": respawned.append(cmd))
    monkeypatch.setattr(panel.pult, "home_of", lambda w: None)
    monkeypatch.setattr(panel, "need_claude", lambda: None)
    panel.revive("@7")
    assert respawned == ["claude --add-dir /r/one --add-dir /r/two --continue"]


def test_space_resume_and_revive_pass_add_dir(panel, monkeypatch):
    panel.t["state"][repos.STATE] = {"/srv/demo/home/projects/s1": ["/srv/demo/home/projects/shop"]}
    monkeypatch.setattr(space_sessions, "check_folder", lambda slug, f: Path("/srv/demo/home/projects") / f)
    monkeypatch.setattr(space_sessions, "is_open", lambda slug, p: False)
    monkeypatch.setattr(space_sessions, "listing", lambda slug: [{"folder": "s1"}])
    monkeypatch.setattr(space_sessions, "has_history", lambda slug, p: True)
    monkeypatch.setattr(panel, "space_windows", lambda slug: [])
    got = []
    monkeypatch.setattr(webapp.tenants, "new_window", lambda slug, name, path, args="": got.append(args) or "@3")
    panel.space_resume("demo", "s1")
    assert got == ["--add-dir /srv/demo/home/projects/shop --continue"]
    monkeypatch.setattr(webapp.tenants, "load", lambda slug: {"slug": slug})
    monkeypatch.setattr(webapp.tenants, "command", lambda t: "claude-space")
    respawned = []
    monkeypatch.setattr(panel.tmux, "window", lambda wid: {"id": wid, "stopped": True, "mark": "glm", "space": "demo",
                                                           "path": "/srv/demo/home/projects/s1"})
    monkeypatch.setattr(panel.tmux, "respawn", lambda wid, path, cmd, mark="": respawned.append(cmd))
    panel.revive("t:demo:@3")
    assert respawned == ["claude-space --add-dir /srv/demo/home/projects/shop --continue"]


def test_detach_keeps_folder(panel):
    w = {"id": "@1", "name": "a", "path": "/p/a", "cmd": "claude"}
    path = panel.repo_add(w, "acme/shop")["path"]
    assert panel.repo_remove(w, path) == {"added": []}
    assert Path(path).is_dir()                                              # папка с репозиторием осталась
    panel.restart(w, "claude")
    assert "--add-dir" not in panel.t["opened"][-1]
    with pytest.raises(LookupError):
        panel.repo_remove(w, path)


def test_stopped_session_only_remembers(panel):
    w = {"id": "@1", "name": "a", "path": "/p/a", "stopped": True, "cmd": "bash"}
    d = panel.repo_add(w, "acme/shop")
    assert d["sent"] is False and panel.t["sent"] == [] and len(d["added"]) == 1


def test_list_without_space_token_gives_hint(panel, monkeypatch):
    def no(slug, sh=None):
        raise repos.NoToken(slug)
    monkeypatch.setattr(repos, "space_list", no)
    d = panel.repo_list({"id": "t:demo:@1", "path": "/srv/demo/home/projects/s1", "space": "demo"})
    assert d["repos"] == [] and d["hint"]["url"].startswith("https://github.com/settings/personal-access-tokens")
    assert d["space"] == "demo"


# ---------- фокус: только своя сессия ----------
W = {"@1": {"id": "@1", "name": "a", "path": "/p/a", "cmd": "claude", "profile": "claude"},
     "@2": {"id": "@2", "name": "b", "path": "/p/b", "cmd": "claude", "profile": "claude"}}


class Wins:
    def __init__(self):
        self.w = {k: dict(v) for k, v in W.items()}

    def window(self, wid):
        return self.w.get(str(wid))

    def windows(self):
        return list(self.w.values())

    @contextlib.contextmanager
    def scope(self, slug):
        yield

    all_spaces = contextlib.nullcontext


@pytest.fixture
def server(panel, monkeypatch):
    p = panel
    p.people.accept(1)
    p.people.set_country(1, chosen="NL")
    wins = Wins()
    monkeypatch.setattr(p, "tmux", wins)
    monkeypatch.setattr(p, "window", lambda wid: wins.window(wid))
    monkeypatch.setattr(p, "sessions", lambda pool=None: [{"id": w["id"], "name": w["name"]} for w in wins.windows()])
    monkeypatch.setattr(repos, "owner_list", lambda: [{"full": "acme/shop", "private": False, "about": ""}])
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"p": p, "base": f"http://127.0.0.1:{srv.server_address[1]}", "tok": p.auth.issue(1)}
    srv.shutdown()


def call(base, path, body=None, cookie="", headers=None):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": cookie, **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read()), r.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), ""


def test_focus_repos_only_own_session(server):
    s, fx = server, {focus.HEADER: "1"}
    owner = f"{webauth.COOKIE}={s['tok']}"
    code, d, _ = call(s["base"], "/api/focus/new", {"w": "@1", "base": s["base"]}, owner)
    assert code == 200
    _, _, setc = call(s["base"], "/api/focus/open", {"token": d["url"].split("#focus=")[1]}, "", fx)
    cookie = setc.split(";")[0]
    code, d, _ = call(s["base"], "/api/repos?w=@1", None, cookie, fx)
    assert code == 200 and d["repos"][0]["full"] == "acme/shop"
    code, d, _ = call(s["base"], "/api/repos/add", {"w": "@1", "repo": "acme/shop"}, cookie, fx)
    assert code == 200 and d["sent"] and s["p"].t["sent"] == [("@1", f"/add-dir {d['path']}")]
    for path, body in (("/api/repos/add", {"w": "@2", "repo": "acme/shop"}),
                       ("/api/repos/remove", {"w": "@2", "path": d["path"]}), ("/api/repos/add", {"repo": "acme/x"})):
        code, r, _ = call(s["base"], path, body, cookie, fx)
        assert code == 403 and r["code"] == "focus_scope", (path, r)
    assert call(s["base"], "/api/repos?w=@2", None, cookie, fx)[0] == 403
    assert s["p"].t["fetched"] == ["acme/shop"]                            # чужой сессии — ни клона, ни /add-dir
    code, r, _ = call(s["base"], "/api/repos/remove", {"w": "@1", "path": d["path"]}, cookie, fx)
    assert code == 200 and r["added"] == []
    code, r, _ = call(s["base"], "/api/repos?w=@2", None, owner)            # владелец в пульте — любую свою
    assert code == 200
