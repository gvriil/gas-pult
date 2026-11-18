"""Без технических вопросов человеку (владелец 18.11).

1. Открыл спящую сессию — она просыпается сама (``/api/revive`` будит заглушку claude-sleep пустым Enter).
2. Вопрос Claude Code «доверять папке?» в новой сессии пульт закрывает сам — только если курсор на «Yes, I trust».
3. Памяти мало — перед новой или проснувшейся сессией в фоне усыпляются простаивающие (claude-sleep auto, 15 мин).
"""

import shutil
import subprocess
import tempfile
import time

import pytest

from gas_pult import tmux as tmux_mod
from gas_pult import webapp
from gas_pult.config import Config
from gas_pult.tmux import Tmux


def test_free_mb_reads_memavailable(tmp_path):
    f = tmp_path / "meminfo"
    f.write_text("MemTotal:       14587000 kB\nMemFree:  100 kB\nMemAvailable:    1536000 kB\n")
    assert tmux_mod.free_mb(str(f)) == 1500
    assert tmux_mod.free_mb(str(tmp_path / "нет")) is None


def test_make_room_only_when_low_and_sleeper_present(monkeypatch):
    calls = []
    monkeypatch.setattr(tmux_mod.subprocess, "Popen", lambda cmd, **kw: calls.append((cmd, kw["env"])))
    monkeypatch.setattr(tmux_mod, "sleeper", lambda: "/x/claude-sleep")
    monkeypatch.setattr(tmux_mod, "free_mb", lambda: 5000)
    assert tmux_mod.make_room(2000) is False and calls == []          # памяти хватает — никого не трогаем
    monkeypatch.setattr(tmux_mod, "free_mb", lambda: 900)
    assert tmux_mod.make_room(2000) is True
    cmd, env = calls[-1]
    assert cmd == ["/x/claude-sleep", "auto"] and env["CLAUDE_SLEEP_HOURS"] == "0.25"
    monkeypatch.setattr(tmux_mod, "sleeper", lambda: "")
    assert tmux_mod.make_room(2000) is False                          # claude-sleep не стоит — молча ничего


@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    return webapp.Panel(Config(token="1:T", owners=[1], models=["opus"]))


def test_revive_wakes_sleeping_window_without_respawn(panel, monkeypatch):
    woke, respawned = [], []
    monkeypatch.setattr(panel.tmux, "window", lambda wid: {"id": wid, "sleep": True, "mark": "claude", "path": "/p"})
    monkeypatch.setattr(panel.tmux, "wake_open", lambda wid: woke.append(wid))
    monkeypatch.setattr(panel.tmux, "respawn", lambda *a, **kw: respawned.append(a))
    assert panel.revive("@4") == {"id": "@4", "woke": True}
    assert woke == ["@4"] and respawned == []                         # тот же процесс-заглушка, не новый Claude


def test_revive_still_refuses_live_session(panel, monkeypatch):
    monkeypatch.setattr(panel.tmux, "window", lambda wid: {"id": wid, "mark": "claude", "path": "/p"})
    with pytest.raises(ValueError):
        panel.revive("@4")


DIALOG = """import sys
print("Do you trust the files in this folder?")
print("")
print("{cur} 1. Yes, I trust this folder")
print("  2. No, exit")
sys.stdout.flush()
open(sys.argv[1], "a").write(repr(sys.stdin.readline()) + "\\n")
"""


@pytest.fixture
def tm(monkeypatch):
    if not shutil.which("tmux"):
        pytest.skip("нужен tmux")
    d = tempfile.mkdtemp(prefix="gp-", dir="/tmp")
    monkeypatch.setenv("GAS_PULT_TMUX_SOCKET", d + "/s")
    yield Tmux("t")
    subprocess.run(["tmux", "-S", d + "/s", "kill-server"], capture_output=True)
    shutil.rmtree(d, ignore_errors=True)


def _run_dialog(tm, tmp_path, cur):
    script, got = tmp_path / "dlg.py", tmp_path / "got.txt"
    script.write_text(DIALOG.replace("{cur}", cur))
    wid = tm.new_window("trust", str(tmp_path), f"python3 -I {script} {got}")
    return wid, got


def test_trust_dialog_answered_yes_by_itself(tm, tmp_path):
    _wid, got = _run_dialog(tm, tmp_path, "❯")
    end = time.time() + 10
    while time.time() < end and not (got.exists() and got.read_text()):
        time.sleep(0.2)
    assert got.exists() and got.read_text() == "'\\n'\n"                # Enter на «Yes, I trust»


def test_trust_dialog_not_touched_when_cursor_elsewhere(tm, tmp_path):
    wid, got = _run_dialog(tm, tmp_path, " ")                         # курсор не на «Yes» — не жмём
    assert tm.accept_trust(wid, wait=2, step=0.3) is False
    assert not (got.exists() and got.read_text())                     # Enter не нажат
