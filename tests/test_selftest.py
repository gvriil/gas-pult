"""Задача 38: что работает у поставщика (models.CAPS), интеграции для любой модели (mcp.PRESETS) и автотест
поставщиков (selftest.py). Настоящий claude и живой tmux не трогаем: ``subprocess.run`` подменяется, а в одном тесте
вместо claude — поддельная программа во временной папке (PATH)."""

import json
import os
import stat
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from websrc import web_source

from gas_pult import mcp, models, providers, selftest


@pytest.fixture
def dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    return tmp_path


# ---------- что работает у поставщика ----------
def test_caps_fields_added_to_public(dirs):
    pub = {p["id"]: p for p in models.public({})}
    assert pub["claude"]["limits"] == [] and {"connectors", "websearch"} <= {g["id"] for g in pub["claude"]["works"]}
    zai = pub["zai"]
    assert [g["id"] for g in zai["limits"]] == ["connectors", "remote", "websearch", "images"]
    assert "claude.ai" in zai["limits"][0]["names"] and zai["alt"] == ["notion", "drive", "websearch"]
    assert zai["alt_names"] == "Notion, Google Диск (rclone), Веб-поиск"
    ds = pub["deepseek"]                                    # DeepSeek сам поддерживает веб-поиск Claude Code
    assert "websearch" in {g["id"] for g in ds["works"]} and "websearch" not in ds["alt"]
    assert "websearch" in {g["id"] for g in pub["openrouter"]["unsure"]}
    for p in pub.values():                                  # старые поля на месте — API только дополнен
        assert {"id", "title", "needs_key", "key", "main", "fast", "not_ready"} <= p.keys()


def test_every_alt_is_a_preset_for_any_provider():
    ids = {p["id"]: p for p in mcp.PRESETS}
    for alts in models.ALT.values():
        for a in alts:
            assert ids[a]["providers"] == "all"
    for c in mcp.CONNECTORS:                                # коннекторы claude.ai — только Claude
        assert c["providers"] == "claude" and (not c["alt"] or c["alt"] in ids)
    assert all(p["providers"] == "all" for p in mcp.PRESETS)


def test_context_windows_have_room_for_answer():
    # окно GLM-5.3 и DeepSeek V4 — 1M, ответ до 128K/384K: сжимать раньше, как советует DeepSeek (786432)
    for pid in ("zai", "deepseek"):
        assert models.BY_ID[pid]["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "786432"


# ---------- интеграции для любой модели ----------
class Fake:
    def __init__(self):
        self.calls = []

    def __call__(self, *args, home=None, env=None):
        self.calls.append((args, env))
        out = "gdrive: https://drivemcp.googleapis.com/mcp/v1 (HTTP) - ⚠ Needs authentication\n"
        return subprocess.CompletedProcess(args, 0, out if args[0] == "list" else "", "")


def test_gdrive_oauth_client_secret_not_in_args(monkeypatch):
    f = Fake()
    monkeypatch.setattr(mcp, "_claude", f)
    res = mcp.Mcp().add("gdrive", "gdrive", {"client_id": "123-abc.apps.googleusercontent.com",
                                             "client_secret": "GOCSPX-secret"})
    args, env = f.calls[0]
    assert args[:2] == ("add-json", "gdrive") and args[3:] == ("-s", "user", "--client-secret")
    assert json.loads(args[2]) == {"type": "http", "url": "https://drivemcp.googleapis.com/mcp/v1",
                                   "oauth": {"clientId": "123-abc.apps.googleusercontent.com"}}
    assert env == {"MCP_CLIENT_SECRET": "GOCSPX-secret"} and "GOCSPX" not in " ".join(args)
    assert "не отвечает" in res                            # панель покажет «Войти»
    with pytest.raises(ValueError, match="ID клиента"):
        mcp.Mcp().add("gdrive", "gdrive", {"client_id": "bad id", "client_secret": "x"})


def test_atlassian(monkeypatch):
    f = Fake()
    monkeypatch.setattr(mcp, "_claude", f)
    mcp.Mcp().add("atlassian", "atlassian", {})
    adds = [(json.loads(a[2]), e) for a, e in f.calls if a[0] == "add-json"]
    assert adds[0] == ({"type": "http", "url": "https://mcp.atlassian.com/v1/mcp"}, None)


def test_claude_helper_passes_env_only_when_given(monkeypatch):
    seen = []
    monkeypatch.setattr(mcp.subprocess, "run", lambda cmd, **kw: seen.append(kw["env"]) or
                        subprocess.CompletedProcess(cmd, 0, "", ""))
    mcp._claude("list")
    mcp._claude("add-json", "x", "{}", env={"MCP_CLIENT_SECRET": "s"})
    assert seen[0] is None and seen[1]["MCP_CLIENT_SECRET"] == "s"


# ---------- автотест ----------
def stream(word="", token="", tools=("Read", "Bash", "WebFetch", "WebSearch"), calls=("Read", "WebFetch"),
           errors=(), result=None, is_error=False):
    ev = [{"type": "system", "subtype": "init", "tools": list(tools), "model": "glm-5.3"}]
    for i, c in enumerate(calls):
        ev.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": c}]}})
        ev.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{i}",
                                                            "is_error": c in errors}]}})
    text = result if result is not None else f"CODEWORD: {word}\nFILE: {token}\nFETCH: Example Domain"
    ev.append({"type": "result", "subtype": "success", "is_error": is_error, "result": text, "total_cost_usd": 0.004})
    return "\n".join(json.dumps(e) for e in ev) + "\n"


def fake_run(**over):
    """Подмена subprocess.run: читает CLAUDE.md и probe.txt из папки проверки и отвечает как claude -p."""
    seen = []

    def run(cmd, input, capture_output, text, timeout, cwd, env):
        seen.append({"cmd": cmd, "cwd": cwd, "input": input})
        w = Path(cwd)
        word = (w / "CLAUDE.md").read_text().split(": ")[-1].strip()
        token = (w / "probe.txt").read_text().strip()
        return subprocess.CompletedProcess(cmd, 0, stream(word, token, **over), "")
    run.seen = seen
    return run


def test_run_one_all_pass_and_flags(dirs):
    providers.save_key("zai", "zai-secret-key-123")
    run = fake_run()
    r = selftest.run_one("zai", {}, run)
    assert r["checks"] == {"memory": True, "tools": True, "tool": True, "webfetch": True} and not r["error"]
    assert r["cost"] == 0.004 and r["websearch_tool"]
    cmd = run.seen[0]["cmd"]
    assert cmd[:2] == ["claude", "--settings"] and "zai-secret-key-123" not in " ".join(cmd)
    for flag in ("-p", "--no-session-persistence", "--strict-mcp-config", "--max-turns", "--max-budget-usd"):
        assert flag in cmd
    assert cmd[cmd.index("--setting-sources") + 1] == "project,local"            # без хуков пользователя
    assert not Path(run.seen[0]["cwd"]).exists()                                # временная папка убрана


def test_run_one_detects_failures(dirs):
    providers.save_key("zai", "k")
    r = selftest.run_one("zai", {}, fake_run(calls=("Read",), tools=()))      # WebFetch не вызывал, инструментов нет
    assert r["checks"] == {"memory": True, "tools": False, "tool": True, "webfetch": False}
    r = selftest.run_one("zai", {}, fake_run(errors=("WebFetch",)))            # WebFetch вернул ошибку
    assert not r["checks"]["webfetch"]
    r = selftest.run_one("zai", {}, fake_run(result="CODEWORD: нет\nFILE: угадал\nFETCH: Example Domain",
                                              calls=("WebFetch",)))
    assert not r["checks"]["memory"] and not r["checks"]["tool"]              # без вызова Read строку не угадать
    r = selftest.run_one("zai", {}, fake_run(result="API Error: 401", is_error=True, calls=(), tools=()))
    assert r["error"] == "API Error: 401" and not any(r["checks"].values())


def test_run_one_errors_without_claude_or_key(dirs):
    def missing(*a, **k):
        raise FileNotFoundError
    providers.save_key("zai", "k")
    assert selftest.run_one("zai", {}, missing)["error"] == "Claude Code не установлен"

    def slow(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, 1)
    assert "нет ответа" in selftest.run_one("zai", {}, slow)["error"]
    assert "нет ключа" in selftest.run_one("deepseek", {}, fake_run())["error"]


def test_targets_due_run_all_public_summary(dirs):
    data = dirs / "data"
    assert selftest.targets({}) == [] and not selftest.due(data, {})
    providers.save_key("zai", "k")
    providers.save_key("gigachat", "k")                     # шлюз без адреса — не проверяем
    assert selftest.targets({}) == ["zai"] and selftest.due(data, {})
    pub = selftest.public(data, {})
    assert pub["profiles"][0]["t"] is None and "ещё не проверялся" in selftest.summary(data, {})
    d = selftest.run_all(data, {}, fake_run(calls=("Read",)))
    assert d["t"] and "running" not in selftest.load(data) and not selftest.due(data, {})
    p = selftest.public(data, {})["profiles"][0]
    assert p["id"] == "zai" and not p["ok"] and p["checks"]["memory"] and not p["checks"]["webfetch"]
    assert "WebFetch" in selftest.summary(data, {}) and "❌" in selftest.summary(data, {})
    assert (data / "selftest.json").stat().st_mode & 0o777 == 0o600


def test_run_all_once_at_a_time(dirs):
    data = dirs / "data"
    providers.save_key("zai", "k")
    selftest.save(data, {"running": int(__import__("time").time())})
    run = fake_run()
    assert selftest.run_all(data, {}, run) == selftest.load(data) and run.seen == []
    assert not selftest.start(data, {}, run)
    selftest.save(data, {"running": 1})                      # старая отметка (процесс умер) — не мешает
    assert selftest.run_all(data, {}, run)["results"]["zai"]["checks"]["tool"]


def test_run_all_clears_running_on_crash(dirs):
    data = dirs / "data"
    providers.save_key("zai", "k")

    def boom(*a, **k):
        raise RuntimeError("сбой")
    with pytest.raises(RuntimeError):
        selftest.run_all(data, {}, boom)
    assert not selftest.running(selftest.load(data))


def test_with_fake_claude_program(dirs, monkeypatch):
    """Настоящий запуск подпроцесса, но вместо claude — своя программа во временной папке."""
    providers.save_key("deepseek", "k")
    bindir = dirs / "bin"
    bindir.mkdir()
    prog = bindir / "claude"
    prog.write_text(f"""#!{sys.executable}
import json, sys
from pathlib import Path
assert "--settings" in sys.argv and sys.stdin.read().startswith("Это автоматическая проверка")
word = Path("CLAUDE.md").read_text().split(": ")[-1].strip()
tok = Path("probe.txt").read_text().strip()
ev = [{{"type": "system", "subtype": "init", "tools": ["Read", "Edit", "WebFetch"]}},
      {{"type": "assistant", "message": {{"content": [{{"type": "tool_use", "id": "a", "name": "Read"}},
                                                       {{"type": "tool_use", "id": "b", "name": "WebFetch"}}]}}}},
      {{"type": "result", "subtype": "success",
        "result": f"**CODEWORD:** {{word}}\\nFILE: {{tok}}\\nFETCH: Example Domain"}}]
print("\\n".join(json.dumps(e) for e in ev))
""")
    prog.chmod(prog.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    r = selftest.run_one("deepseek", {})
    assert r["checks"] == {"memory": True, "tools": True, "tool": True, "webfetch": True}, r
    assert not r["websearch_tool"]


def test_api_selftest_owner_only(dirs, monkeypatch):
    from gas_pult import webapp, webauth
    from gas_pult.config import Config
    panel = webapp.Panel(Config(token="1:T", owners=[1], region="NL"))
    for uid, role in ((1, None), (2, "member")):
        if role:
            panel.people.add(uid, role)
        panel.people.accept(uid)
        panel.people.set_country(uid, chosen="NL")
    started = []
    monkeypatch.setattr(selftest, "start", lambda data, state: started.append(data) or True)
    providers.save_key("zai", "k")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/api/selftest"

    def call(body=None, uid=1):
        hdr = {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={panel.auth.issue(uid)}"}
        req = urllib.request.Request(base, json.dumps(body).encode() if body is not None else None, hdr)
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    try:
        d = call()
        assert d["checks"] == list(selftest.CHECKS) and [p["id"] for p in d["profiles"]] == ["zai"]
        assert call({})["started"] and started
        with pytest.raises(urllib.error.HTTPError) as e:
            call(uid=2)
        assert e.value.code == 403
    finally:
        srv.shutdown()


def test_ui_wiring():
    page = web_source()
    for s in ("paintGaps(s);", "providersView", "/api/selftest", "gapPick(p)", "connAlt(c)", 'T("int.any.title")'):
        assert s in page, s
    ru = json.loads((Path(selftest.__file__).parent / "web" / "i18n" / "ru.json").read_text(encoding="utf-8"))
    for g in {g for c in models.CAPS.values() for k in ("limits", "unsure") for g in c[k]}:
        assert f"gap.{g}" in ru and f"gap.s.{g}" in ru, g
    for g in {g for c in models.CAPS.values() for g in c["works"]}:
        assert f"work.{g}" in ru, g
    for c in selftest.CHECKS:
        assert f"st.check.{c}" in ru


# ---------- базовые интеграции на любой модели (задача 48) ----------
def test_run_base_uses_own_servers_and_judges_by_files(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, input, cwd, **kw):
        seen["cmd"] = cmd
        seen["cfg"] = json.loads(Path(cmd[cmd.index("--mcp-config") + 1]).read_text())
        out = [{"type": "system", "subtype": "init", "tools": ["Read", "mcp__search__web_search"]},
               {"type": "assistant", "message": {"content": [
                   {"type": "tool_use", "id": "1", "name": "mcp__search__web_search", "input": {}},
                   {"type": "tool_use", "id": "2", "name": "mcp__drive__drive_list", "input": {}}]}},
               {"type": "result", "subtype": "success", "result": "DOWNLOADED: -", "total_cost_usd": 0.01}]
        return subprocess.CompletedProcess(cmd, 0, "\n".join(json.dumps(e) for e in out), "")

    monkeypatch.setattr(selftest.models, "command", lambda base, profile, state: "claude")
    r = selftest.run_base("zai", {}, run=fake_run, rclone="/bin/true")
    assert r["checks"] == {"search": True, "summary": False, "list": True, "download": False}
    cmd, cfg = seen["cmd"], seen["cfg"]
    assert "--strict-mcp-config" in cmd and "--no-session-persistence" in cmd
    srv = cfg["mcpServers"]
    assert srv["search"]["args"][1] == "search" and srv["search"]["env"]["GAS_SEARCH_BASE"].startswith("http://127.")
    assert srv["drive"]["env"]["GAS_DRIVE_RCLONE"] == "/bin/true" and r["cost"] == 0.01
