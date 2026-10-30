"""Сквозной тест без сети: настоящий tmux (изолированный сервер), фальшивый `claude`, фальшивый Telegram."""

import json
import os
import shutil
import threading
import time

import pytest

from gas_pult import transcripts
from gas_pult.bot import Pult
from gas_pult.config import Config

pytestmark = pytest.mark.skipif(not shutil.which("tmux"), reason="нужен tmux")


class FakeApi:
    def __init__(self):
        self.calls = []

    def __call__(self, method, files=None, **params):
        self.calls.append((method, params))
        return {"username": "test_bot"} if method == "getMe" else {}

    def redact(self, text):
        return str(text)

    def texts(self):
        return [p.get("text", "") for m, p in self.calls if m == "sendMessage"]


def wait(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


@pytest.fixture
def pult(tmp_path, monkeypatch):
    monkeypatch.setenv("TMUX_TMPDIR", str(tmp_path / "tmux"))       # свой сервер tmux, чужие окна не видны
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", tmp_path / "claude-projects")
    (tmp_path / "tmux").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"            # «Claude»: показывает приглашение и печатает всё введённое
    fake.write_text("#!/usr/bin/env bash\nwhile true; do printf '❯ '; read -r line; echo \"got: $line\"; done\n")
    fake.chmod(0o755)
    proj = tmp_path / "projects" / "demo"
    proj.mkdir(parents=True)
    cfg = Config(token="t", owners=[1], session="test", claude=str(fake), host="box",
                 project_roots=[str(tmp_path / "projects")])
    p = Pult(cfg)
    p.api = FakeApi()
    p.home = str(tmp_path)
    yield p, proj
    os.system(f"TMUX_TMPDIR={tmp_path / 'tmux'} tmux kill-server 2>/dev/null")


def msg(text):
    return {"message_id": 1, "chat": {"id": 1}, "from": {"id": 1}, "text": text}


def test_new_session_send_and_receive(pult):
    p, proj = pult
    p.open_session(1, "demo-1", str(proj))
    assert wait(lambda: (p.active() or {}).get("path") == str(proj))   # tmux узнаёт папку не мгновенно
    w = p.active()
    assert w["cmd"] == "claude" and w["name"] == "demo-1"
    assert any("активно" in t for t in p.api.texts())

    p.on_message(msg("привет, Claude"))                      # Telegram → окно
    assert wait(lambda: "got: привет, Claude" in "\n".join(p.tmux.screen(w["id"])))

    threading.Thread(target=p.monitor, daemon=True).start()  # транскрипт → Telegram
    time.sleep(1)
    d = transcripts.project_dir(str(proj))
    d.mkdir(parents=True)
    rows = [{"type": "user", "message": {"content": "вопрос"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "."}], "stop_reason": "end_turn"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Готово:\n```bash\necho ok\n```"}],
                                              "stop_reason": "end_turn"}}]
    (d / "s.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert wait(lambda: any(t.startswith("[demo-1]\nГотово") for t in p.api.texts()))
    assert not any(t == "[demo-1]\n." for t in p.api.texts())            # точку не прислали
    assert wait(lambda: any("команда 1/1" in t for t in p.api.texts()))  # команда — отдельным сообщением


def test_settings_reject_unknown_values(pult):
    p, _ = pult
    p.on_callback({"id": "q", "from": {"id": 1}, "message": {"chat": {"id": 1}}, "data": "set:notify=everything"})
    p.on_callback({"id": "q", "from": {"id": 1}, "message": {"chat": {"id": 1}}, "data": "set:owners=1"})
    assert p.state()["notify"] == "all" and "owners" not in p.state()
    p.on_callback({"id": "q", "from": {"id": 1}, "message": {"chat": {"id": 1}}, "data": "set:notify=off"})
    assert p.state()["notify"] == "off"


@pytest.mark.parametrize("argv, ok", [
    (["claude", "--resume"], True),
    (["/home/u/.local/bin/claude"], True),
    (["node", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"], True),
    (["bash", "/tmp/claude"], True),
    (["bash"], False),
    (["vim", "claude.md"], False),
])
def test_is_claude(argv, ok):
    from gas_pult.tmux import is_claude
    assert is_claude(argv) is ok


def test_one_window_per_project(pult):
    p, proj = pult
    p.open_session(1, "demo-1", str(proj))
    assert wait(lambda: (p.active() or {}).get("path") == str(proj))
    first = p.active()["id"]
    p.open_session(1, "demo-2", str(proj))                  # вторая сессия в той же папке — не создаётся
    assert p.active()["id"] == first
    assert len([w for w in p.tmux.windows() if w["cmd"] == "claude"]) == 1
    assert "уже работает «demo-1»" in p.api.texts()[-1]
