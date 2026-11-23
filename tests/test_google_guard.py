"""Данные Google — только моделям, которые на них не учатся (правило 17.11, решение штаба 23.11 «вариант а»).

Окно FCC (и любого профиля, которому base_mcp.learns_on_data запрещает данные Google) — без серверов Google
(--strict-mcp-config) и с хуком, который закрывает ~/drive. Профиль «claude» — как раньше."""

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gas_pult import base_mcp, google_guard, models, providers, secrets_guard

FAKE = {
    "mcpServers": {
        "gdrive": {"type": "http", "url": "https://drivemcp.googleapis.com/mcp/v1",
                   "headers": {"Authorization": "Bearer test-not-a-key"}},
        "google-drive": {"type": "stdio", "command": "/usr/bin/python3", "args": ["/opt/x/base_mcp.py", "drive"],
                         "env": {"RCLONE_CONFIG": "/opt/x/rclone.conf", "GAS_DRIVE_REMOTE": "gdrive"}},
        "my-disk": {"type": "stdio", "command": "rclone", "args": ["serve", "mcp"]},
        "sheets": {"type": "http", "url": "https://sheets.googleapis.com/mcp"},
        "github": {"type": "http", "url": "https://api.githubcopilot.com/mcp/"},
        "context7": {"type": "http", "url": "https://mcp.context7.com/mcp"},
        "search": {"type": "stdio", "command": "/usr/bin/python3", "args": ["/opt/x/base_mcp.py", "search"]},
    },
    "projects": {},
}


@pytest.fixture
def home(monkeypatch, tmp_path):
    """Домашняя папка теста: ~/drive — символьная ссылка на «точку монтирования» rclone, свой .claude.json."""
    h = tmp_path / "h"
    (h / "mnt" / "gd").mkdir(parents=True)
    (h / "mnt" / "gd" / "x.txt").write_text("тайна Диска")
    (h / "drive").symlink_to(h / "mnt" / "gd")
    (h / "proj").mkdir()
    (h / "proj" / "a.txt").write_text("обычный файл")
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("GAS_PULT_DRIVE_ROOT", raising=False)
    monkeypatch.setattr(secrets_guard, "rclone_mounts", lambda *a: [])
    cj = h / ".claude.json"
    fake = json.loads(json.dumps(FAKE))
    fake["mcpServers"]["docs"] = {"type": "stdio", "command": "/usr/bin/python3",
                                  "args": ["/opt/x/docs_mcp.py", str(h / "drive" / "Проекты")]}
    fake["projects"][str(h / "proj")] = {"mcpServers": {"local-one": {"type": "http", "url": "http://127.0.0.1:9/mcp"}},
                                         "enabledMcpjsonServers": ["shared-ok"]}
    cj.write_text(json.dumps(fake))
    (h / "proj" / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "shared-ok": {"type": "http", "url": "http://127.0.0.1:8/mcp"},
        "shared-unapproved": {"type": "http", "url": "http://127.0.0.1:7/mcp"},
        "gmail": {"type": "http", "url": "http://127.0.0.1:6/mcp"}}}))
    monkeypatch.setenv("GAS_PULT_CLAUDE_JSON", str(cj))
    return h


@pytest.fixture
def fcc_up(monkeypatch):
    monkeypatch.setattr(models, "local_token", lambda p: "fcc-local-token")
    monkeypatch.setattr(models, "local_up", lambda p: True)


def _mcp_file(cmd: str):
    parts = cmd.split()
    assert "--strict-mcp-config" in parts, cmd
    return parts[parts.index("--mcp-config") + 1]


def test_fcc_window_has_no_google_servers(home, fcc_up):
    cmd = models.command("claude", "fcc", {}, path=str(home / "proj"))
    f = _mcp_file(cmd)
    assert os.stat(f).st_mode & 0o777 == 0o600
    names = set(json.loads(Path(f).read_text())["mcpServers"])
    assert names == {"github", "context7", "search", "local-one", "shared-ok"}, names
    assert not names & {"gdrive", "google-drive", "my-disk", "sheets", "docs", "gmail"}
    assert "fcc-local-token" not in cmd


def test_fcc_profile_settings_have_drive_hook(home, fcc_up):
    models.command("claude", "fcc", {})
    s = json.loads((models.profiles_dir() / "fcc.json").read_text())
    (group,) = s["hooks"]["PreToolUse"]
    assert group["matcher"] == "*" and "drive-hook" in group["hooks"][0]["command"]
    assert str(home / "mnt" / "gd") in group["hooks"][0]["command"]           # реальный путь ссылки ~/drive


def test_claude_profile_unchanged(home):
    assert models.command("claude", "claude", {}) == "claude"
    assert models.command("claude", "", {}, path=str(home / "proj")) == "claude"


def test_models_that_do_not_learn_keep_their_servers(home, monkeypatch):
    providers.save_key("zai", "zai-test-key-123456")
    cmd = models.command("claude", "zai", {}, path=str(home / "proj"))
    assert "--strict-mcp-config" not in cmd
    assert "hooks" not in json.loads((models.profiles_dir() / "zai.json").read_text())


def test_deepseek_and_openrouter_also_closed(home):
    providers.save_key("deepseek", "ds-test-key-123456")
    providers.save_key("openrouter", "or-test-key-123456")
    for pid in ("deepseek", "openrouter"):
        assert "--strict-mcp-config" in models.command("claude", pid, {}), pid


def test_learns_rule_lives_in_one_place():
    """Правило «учится на данных» — только base_mcp.learns_on_data; профили спрашивают его же."""
    src = "".join(inspect.getsource(f) for f in (models.google_blocked, models.command, google_guard.flags,
                                                  google_guard.safe_servers, google_guard.hooks))
    assert "learns_on_data" in src and ":free" not in src and "deepseek" not in src.lower()
    for p in models.PROFILES:
        expect = None if p["id"] == "claude" else base_mcp.learns_on_data(models.env_of(p, "", {}))
        assert models.google_blocked(p["id"], {}) == expect, p["id"]
    assert models.google_blocked("fcc") and not models.google_blocked("claude") and not models.google_blocked("zai")


# ---------- хук: папка Диска закрыта ----------
def deny(tool, inp, cwd):
    out = secrets_guard.drive_handle({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": inp,
                                      "cwd": str(cwd)}, secrets_guard.drive_roots())
    return bool(out) and out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_denies_drive_paths(home):
    proj = home / "proj"
    (proj / "lnk").symlink_to(home / "drive")
    assert deny("Read", {"file_path": "~/drive/x.txt"}, proj)
    assert deny("Read", {"file_path": str(home / "drive" / "x.txt")}, proj)
    assert deny("Read", {"file_path": str(home / "mnt" / "gd" / "x.txt")}, proj)   # реальный путь монтирования
    assert deny("Read", {"file_path": "lnk/x.txt"}, proj)                           # через символьную ссылку
    assert deny("Bash", {"command": "cat ~/drive/x.txt"}, proj)
    assert deny("Bash", {"command": "grep -r тайна $HOME/drive"}, proj)
    assert deny("Bash", {"command": "cat lnk/x.txt | head"}, proj)
    assert deny("Bash", {"command": "ls"}, home / "drive")                          # окно стоит в папке Диска
    assert deny("Grep", {"pattern": "тайна", "path": "~/drive"}, proj)
    assert deny("Glob", {"pattern": "drive/**/*.txt"}, home)
    assert deny("mcp__docs__search", {"query": "x", "path": str(home / "drive")}, proj)


def test_hook_allows_ordinary_files(home):
    proj = home / "proj"
    assert not deny("Read", {"file_path": str(proj / "a.txt")}, proj)
    assert not deny("Bash", {"command": "cat a.txt && ls -la"}, proj)
    assert not deny("Bash", {"command": "ls ~/drive-notes"}, proj)
    assert not deny("Grep", {"pattern": "drive", "path": str(proj)}, proj)
    assert not deny("Write", {"file_path": str(proj / "n.md"), "content": "см. ~/drive/x.txt"}, proj)


def test_hook_runs_as_command(home):
    """Как его вызывает Claude Code: команда из настроек профиля, JSON на входе — отказ на выходе."""
    data = {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "~/drive/x.txt"},
            "cwd": str(home / "proj")}
    p = subprocess.run([sys.executable, secrets_guard.__file__, "drive-hook"], input=json.dumps(data),
                       capture_output=True, text=True, env={**os.environ, "HOME": str(home)}, timeout=20)
    out = json.loads(p.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "Limited Use" in out["permissionDecisionReason"]


def test_rclone_mounts_are_roots(tmp_path, monkeypatch):
    m = tmp_path / "mounts"
    m.write_text("proc /proc proc rw 0 0\ngdrive{ab}:Папка /srv/g\\040d fuse.rclone rw 0 0\n"
                 "ydisk-a: /srv/y fuse.rclone rw 0 0\nwork: /srv/w fuse.rclone rw 0 0\n")
    conf = tmp_path / "rclone.conf"
    conf.write_text("[work]\ntype = drive\nscope = drive\n[ydisk-a]\ntype = yandex\n")
    monkeypatch.setenv("RCLONE_CONFIG", str(conf))
    assert secrets_guard.rclone_mounts(str(m)) == ["/srv/g d", "/srv/w"]          # Яндекс Диск — не Google
