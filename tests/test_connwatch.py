"""Сторож входа коннекторов (connwatch, фаза 1): разбор вывода harness, исключения, переходы, задачи, квитанции,
таймер, база паролей на подделке keepassxc-cli и закрытие базы от агентов. Без настоящих claude, pi, opencode."""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from gas_pult import alerts, bot, chatlog, cli, connwatch, injection_guard, secrets_guard, tasks

# Образцы строк `claude mcp list` (Claude Code 2.1, 22.11), адреса и пути обезличены
CLAUDE_OUT = """Checking MCP server health…

claude.ai Notion: https://mcp.example.com/mcp - ✔ Connected
plugin:telegram:telegram: bun run --cwd /opt/plugins/telegram --shell=bun --silent start - ✘ Failed to connect — \
CONNECTION_CLOSED: Connection closed
plugin:design:slack: https://mcp.example.com/slack (HTTP) - ! Needs authentication
plugin:design:gmail:  (HTTP) - - Not configured
github: https://api.example.com/mcp/ (HTTP) - ✔ Connected
linear: https://mcp.example.com/linear (HTTP) - ! Needs authentication
browser-local: /opt/bin/gas-pult bridge-mcp - ✘ Failed to connect — -32000: браузер не подключён
mail: python3 /opt/gas-pult/src/gas_pult/connectors/mail_mcp.py - ✔ Connected
"""

# `opencode mcp list` 1.x: цвет ESC[90m — серый (адрес), ошибка — без цвета
OC_OUT = ("\x1b[0m\n┌  MCP Servers\n│\n●  ✓ github \x1b[90mconnected\n│      \x1b[90mhttps://api.example.com/mcp/\n│\n"
          "●  ⚠ notion \x1b[90mneeds authentication\n│      \x1b[90mhttps://mcp.example.com/mcp\n│\n"
          "●  ✗ browser-local \x1b[90mfailed\n│      MCP error -32000: мост не подключён\n"
          "│      \x1b[90m/opt/bin/gas-pult bridge-mcp\n│\n●  ○ old \x1b[90mdisabled\n│\n")

PI_OUT = json.dumps({"servers": [
    {"name": "github", "enabled": True, "state": "connected", "tools": ["a"]},
    {"name": "linear", "enabled": True, "state": "needs-auth"},
    {"name": "browser-local", "enabled": True, "state": "failed", "error": "мост не подключён"},
    {"name": "off", "enabled": False, "state": "disabled"}], "errors": []})


def states(items):
    return {c["name"]: c["state"] for c in items}


# ---------- разбор ----------
def test_parse_claude_real_lines():
    items = connwatch.parse_claude(CLAUDE_OUT)
    assert states(items) == {"claude.ai Notion": "ok", "plugin:telegram:telegram": "failed",
                             "plugin:design:slack": "needs_auth", "plugin:design:gmail": "unknown",
                             "github": "ok", "linear": "needs_auth", "browser-local": "failed", "mail": "ok"}
    tg = next(c for c in items if c["name"] == "plugin:telegram:telegram")
    assert tg["harness"] == "claude" and tg["detail"] == "CONNECTION_CLOSED: Connection closed"
    assert all("http" not in c["detail"] for c in items)                 # адрес в detail не попадает


def test_parse_claude_hides_secret_in_error():
    out = "svc: https://x - ✘ Failed to connect — 401 token=ghp_" + "a" * 36
    c = connwatch.parse_claude(out)[0]
    assert c["state"] == "failed" and "ghp_" not in c["detail"]


def test_parse_opencode_and_pi():
    oc = connwatch.parse_opencode(OC_OUT)
    assert states(oc) == {"github": "ok", "notion": "needs_auth", "browser-local": "failed", "old": "unknown"}
    assert next(c for c in oc if c["name"] == "browser-local")["detail"] == "MCP error -32000: мост не подключён"
    pi = connwatch.parse_pi(PI_OUT)
    assert states(pi) == {"github": "ok", "linear": "needs_auth", "browser-local": "failed", "off": "unknown"}
    assert connwatch.parse_pi("не json") == []


def test_collect_marks_unchecked_and_missing(monkeypatch):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout={"claude": CLAUDE_OUT, "pi": PI_OUT}[cmd[0]], stderr="")

    items = connwatch.collect(run=run, which=lambda c: c != "opencode")
    star = {c["harness"]: c["detail"] for c in items if c["name"] == "*"}
    assert set(star) == {"opencode", "hermes"}
    assert "не установлен" in star["opencode"] and star["hermes"].startswith("не проверяется")
    assert ["hermes", "mcp", "list"] not in calls and ["pi", "mcp", "list", "--json"] in calls


# ---------- исключения ----------
def test_excludes_default_and_config(tmp_path):
    (tmp_path / "connwatch.toml").write_text('exclude = ["browser-local", "pi/linear"]\n')
    pats = connwatch.excludes(tmp_path)
    ex = lambda h, n: connwatch.excluded({"harness": h, "name": n}, pats)   # noqa: E731
    assert ex("claude", "plugin:design:slack") and ex("claude", "plugin:gitlab:gitlab")
    assert ex("claude", "browser-local") and ex("pi", "linear") and not ex("claude", "linear")
    assert not ex("claude", "claude.ai Notion")
    assert connwatch.excludes(tmp_path / "нет") == list(connwatch.DEFAULT_EXCLUDE)


# ---------- переходы ----------
def conn(state, name="linear", harness="claude"):
    return [{"harness": harness, "name": name, "state": state, "detail": ""}]


def open_tasks(tmp_path):
    return [t for t in tasks.Tasks(tmp_path / "tasks.json").list() if t["status"] != "done"]


def test_ok_needs_auth_ok_one_task_one_receipt(tmp_path):
    clock = [1000.0]
    w = connwatch.Watch(tmp_path, clock=lambda: clock[0])
    pats = connwatch.DEFAULT_EXCLUDE
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = SimpleNamespace(data=tmp_path, owners=[1])
    p.events = chatlog.Log(tmp_path / "chat-events.jsonl", clock=lambda: clock[0])
    p.sent = []
    p.broadcast = lambda text, kind="error", **kw: p.sent.append(text)
    p.fail_tick(clock[0])                                                # бот: «отсюда»
    assert w.run(conn("ok"), pats) == []
    clock[0] += 1800
    acts = w.run(conn("needs_auth") + conn("needs_auth", "plugin:design:slack"), pats)
    assert len(acts) == 1 and "connector_down" in acts[0]
    ts = open_tasks(tmp_path)
    assert len(ts) == 1 and ts[0]["status"] == "waiting" and ts[0]["title"] == "Войти заново: linear (Claude Code)"
    assert "/mcp" in ts[0]["next"]
    clock[0] += 1800                                                     # всё ещё без входа — ни задачи, ни события
    assert w.run(conn("needs_auth"), pats) == []
    assert len(open_tasks(tmp_path)) == 1
    clock[0] += 400
    p.fail_tick(clock[0])
    assert len(p.sent) == 1 and "«linear» (Claude Code) потерял вход" in p.sent[0]
    clock[0] += 400
    p.fail_tick(clock[0])
    assert len(p.sent) == 1                                              # не чаще раза на переход
    clock[0] += 1800
    acts = w.run(conn("ok"), pats)
    assert len(acts) == 1 and "connector_up" in acts[0]
    assert open_tasks(tmp_path) == []
    clock[0] += 400
    p.fail_tick(clock[0])
    assert len(p.sent) == 2 and "снова на связи" in p.sent[1]
    evs = [json.loads(x) for x in (tmp_path / "chat-events.jsonl").read_text().splitlines()]
    assert [e["ev"] for e in evs] == ["connector_relogin", "connector_down", "connector_up"]
    assert evs[0]["result"] == "failed" and "браузер агента" in evs[0]["reason"]   # тестам Chrome недоступен
    assert set(evs[1]) == {"ts", "ev", "harness", "name", "state"}       # без текстов ошибок
    clock[0] += 1800                                                     # снова отвалился — новая задача
    w.run(conn("failed"), pats)
    ts = open_tasks(tmp_path)
    assert len(ts) == 1 and "не запускается" in ts[0]["next"]


def test_task_not_duplicated_when_state_lost(tmp_path):
    w = connwatch.Watch(tmp_path)
    w.run(conn("needs_auth"))
    (tmp_path / "connwatch_state.json").unlink()
    w.run(conn("needs_auth"))
    assert len(open_tasks(tmp_path)) == 1


def test_unknown_keeps_state_and_removed_closes_task(tmp_path):
    w = connwatch.Watch(tmp_path)
    w.run(conn("needs_auth"))
    assert w.run(conn("unknown")) == [] and len(open_tasks(tmp_path)) == 1
    w.run(conn("ok", name="github", harness="pi"))                       # другой harness — claude не трогаем
    assert len(open_tasks(tmp_path)) == 1
    acts = w.run(conn("ok", name="github"))                              # linear пропал из списка claude
    assert any("больше нет" in a for a in acts) and open_tasks(tmp_path) == []


def test_relogin_success_makes_no_task(tmp_path):
    w = connwatch.Watch(tmp_path, relogin_fn=lambda c, fp=None: connwatch.Result(True))
    acts = w.run(conn("needs_auth"))
    assert "автоматически" in acts[0] and open_tasks(tmp_path) == []


def test_relogin_without_browser_is_human_task():
    r = connwatch.relogin(conn("needs_auth", "claude.ai Notion")[0])
    assert not r.done and "claude.ai" in r.hint and "Коннекторы" in r.hint
    assert "pi mcp login linear" in connwatch.relogin(conn("needs_auth", harness="pi")[0]).hint
    assert "opencode mcp auth linear" in connwatch.relogin(conn("needs_auth", harness="opencode")[0]).hint


def test_dry_run_writes_nothing(tmp_path):
    w = connwatch.Watch(tmp_path)
    acts = w.run(conn("needs_auth"), dry=True)
    assert len(acts) == 1 and "connector_down" in acts[0]
    assert sorted(os.listdir(tmp_path)) == []


def test_cli_dry_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "c"))
    monkeypatch.setattr(connwatch, "collect", lambda: connwatch.parse_claude(CLAUDE_OUT))
    cli.main(["connectors", "watch", "--dry-run"])
    out = capsys.readouterr().out
    assert "plugin:design:slack (исключён)" in out and "было бы" in out and "claude:linear" in out
    assert not (tmp_path / "d").exists()


# ---------- systemd ----------
def test_units_text():
    u = connwatch.units(python="/venv/bin/python", path_env="/usr/bin", src="/src")
    svc, tim = u["gas-pult-connwatch.service"], u["gas-pult-connwatch.timer"]
    assert "Type=oneshot" in svc and "ExecStart=/venv/bin/python -m gas_pult connectors watch" in svc
    assert "Environment=PYTHONPATH=/src" in svc and "Restart" not in svc
    assert "OnUnitActiveSec=30min" in tim and "WantedBy=timers.target" in tim
    assert "PYTHONPATH" not in connwatch.units(python="/p", path_env="/b", src="")["gas-pult-connwatch.service"]


def test_install_writes_units_and_enables_timer(tmp_path):
    calls = []
    files = connwatch.install(run=lambda cmd, **kw: calls.append(cmd), home=tmp_path)
    assert len(files) == 2 and all(os.path.exists(f) for f in files)
    assert ["systemctl", "--user", "enable", "--now", "gas-pult-connwatch.timer"] in calls
    connwatch.install(remove=True, run=lambda cmd, **kw: calls.append(cmd), home=tmp_path)
    assert not any(os.path.exists(f) for f in files)


# ---------- база паролей ----------
@pytest.fixture
def vault_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path


def fake_kp(calls, secret="s3cret-Value"):
    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[1] == "db-create":
            kf, db = cmd[cmd.index("--set-key-file") + 1], cmd[-1]
            for p in (kf, db):
                with open(p, "w") as f:
                    f.write("x")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[1] == "show":
            ok = cmd[-1] == "claude/notion"
            return SimpleNamespace(returncode=0 if ok else 1, stdout=secret + "\n" if ok else "",
                                   stderr="" if ok else "Could not find entry")
        raise AssertionError(cmd)
    return run


def test_vault_init_once_and_get(vault_env, capsys):
    calls = []
    run = fake_kp(calls)
    msg = connwatch.vault_init(run=run)
    db, kf = connwatch.vault_paths()
    assert "создана" in msg and db.exists() and kf.exists()
    assert calls[0] == ["keepassxc-cli", "db-create", "-q", "--set-key-file", str(kf), str(db)]
    assert oct(db.stat().st_mode & 0o777) == "0o600" and oct(kf.stat().st_mode & 0o777) == "0o600"
    assert "уже есть" in connwatch.vault_init(run=run) and len(calls) == 1      # второй раз — ничего
    assert connwatch.vault_get("claude/notion", run=run) == "s3cret-Value"
    assert calls[-1][:9] == ["keepassxc-cli", "show", "-q", "-s", "-a", "password", "--no-password", "-k", str(kf)]
    assert connwatch.vault_get("нет/такой", run=run) is None
    assert "s3cret" not in capsys.readouterr().out


def test_vault_get_without_db(vault_env):
    assert connwatch.vault_get("x", run=lambda *a, **k: pytest.fail("не звать keepassxc-cli")) is None


def test_vault_init_failure(vault_env):
    run = lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="boom")    # noqa: E731
    with pytest.raises(RuntimeError):
        connwatch.vault_init(run=run)


# ---------- база закрыта для агентов ----------
@pytest.mark.parametrize("tool,inp", [
    ("Read", {"file_path": "/home/u/.local/share/gas-pult/connectors.kdbx"}),
    ("Read", {"file_path": "/home/u/.config/gas-pult/connectors.key"}),
    ("Grep", {"pattern": "x", "path": "/home/u/.config/gas-pult/connectors.key"}),
    ("Bash", {"command": "keepassxc-cli show -s --no-password -k ~/.config/gas-pult/connectors.key db.kdbx x"}),
    ("Bash", {"command": "cat ~/.local/share/gas-pult/connectors.kdbx | base64"}),
])
def test_secrets_guard_denies_vault(tool, inp):
    out = secrets_guard.handle({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp})
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "база паролей коннекторов" in out["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("tool,inp", [
    ("Read", {"file_path": "/x/my-connectors.kdbx.md"}),
    ("Read", {"file_path": "/x/docs/CONNECTORS.md"}),
    ("Bash", {"command": "ls -la ~/.local/share/gas-pult/connectors.kdbx"}),
    ("Bash", {"command": "gas-pult connectors vault init"}),
])
def test_secrets_guard_allows_other(tool, inp):
    assert secrets_guard.handle({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp}) is None


@pytest.mark.parametrize("tool,inp", [
    ("Read", {"file_path": "/h/.config/gas-pult/connectors.key"}),          # Pi/OpenCode/Hermes через адаптер
    ("grep", {"pattern": "x", "path": "/h/.local/share/gas-pult/connectors.kdbx"}),
    ("Bash", {"command": "keepassxc-cli ls -k connectors.key connectors.kdbx"}),
])
def test_injection_guard_denies_vault_for_other_harness(tool, inp):
    out = injection_guard.handle({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp,
                                  "session_id": "pi-x"})
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert injection_guard.handle({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                                   "tool_input": {"command": "ls connectors.kdbx"}, "session_id": "x"}) is None


def test_receipt_has_no_detail():
    text = connwatch.receipt([{"ev": "connector_down", "harness": "pi", "name": "linear", "state": "failed"},
                              {"ev": "connector_up", "harness": "claude", "name": "github", "state": "ok"}])
    assert text.splitlines() == ["⚠ Коннектор «linear» (Pi) не запускается — задача в «Ждут вас».",
                                 "✓ Коннектор «github» (Claude Code) снова на связи — вошёл заново, задача закрыта."]


def test_alerts_connectors_first_run_remembers(tmp_path):
    ev = chatlog.Log(tmp_path / "e.jsonl", clock=lambda: 50.0)
    ev.event("connector_down", harness="claude", name="old", state="needs_auth")
    assert alerts.Watch(tmp_path).connectors(ev, now=100.0) == []            # старое не шлём
    assert alerts.Watch(tmp_path).connectors(ev, now=200.0) == []


def test_check_timeout_is_unknown():
    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)
    items = connwatch.check("claude", run=run, which=lambda c: True)
    assert items[0]["name"] == "*" and items[0]["state"] == "unknown" and "TimeoutExpired" in items[0]["detail"]
