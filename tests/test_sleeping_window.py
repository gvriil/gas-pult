"""Спящие окна (claude-sleep, штаб 14.11): заглушка с argv0 «claude» вместо Claude, файла сессии нет.

Было: пульт считал окно обычным Claude и ждал строку ввода «❯» 40 с — отправка падала «окно не готово к вводу»;
вставка (bracketed paste) донесла бы до заглушки маркеры «[200~». Стало: окно видно как «💤 спит», id разговора — из
аргументов заглушки, первое сообщение набирается как с клавиатуры и будит сессию."""

import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import pytest

from gas_pult import bot
from gas_pult.tmux import Tmux

pytestmark = pytest.mark.skipif(not shutil.which("tmux"), reason="нужен tmux")

STUB = """import sys
out = sys.argv[3]
while True:
    line = sys.stdin.readline()
    if not line:
        break
    open(out, "a").write(repr(line) + "\\n")
"""


@pytest.fixture
def tm(tmp_path, monkeypatch):
    d = tempfile.mkdtemp(prefix="gp-", dir="/tmp")
    monkeypatch.setenv("GAS_PULT_TMUX_SOCKET", d + "/s")
    t = Tmux("t")
    yield t, tmp_path
    subprocess.run(["tmux", "-S", d + "/s", "kill-server"], capture_output=True)
    shutil.rmtree(d, ignore_errors=True)


def wait(cond, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


def test_sleeping_window_is_seen_and_woken_by_typing(tm, monkeypatch):
    t, tmp = tm
    sid, got = str(uuid.uuid4()), tmp / "got.txt"
    sleeper = tmp / "claude-sleep"
    sleeper.write_text(STUB)
    cmd = f"bash -c 'exec -a claude python3 -I {sleeper} stub {sid} {got}'"   # как у claude-sleep
    wid = t.new_window("arenda", str(tmp), cmd)
    assert wait(lambda: (t.window(wid) or {}).get("sleep"))
    w = t.window(wid)
    assert w["cmd"] == "claude" and w["sid"] == sid and not w.get("live")
    p = bot.Pult.__new__(bot.Pult)
    p.tmux, p.locks = t, tmp / "locks"
    p.actor.uid = None
    p.to_claude(w, "Привет, проснись\nи посмотри логи")
    assert wait(lambda: got.exists() and "посмотри логи" in got.read_text())
    text = got.read_text()
    assert "Привет, проснись" in text and "[200~" not in text and "\\x1b" not in text   # без маркеров вставки


def test_awake_window_is_not_sleeping(tm):
    t, tmp = tm
    fake = tmp / "claude"
    fake.write_text("#!/usr/bin/env bash\nwhile true; do printf '❯ '; read -r line; done\n")
    fake.chmod(0o755)
    wid = t.new_window("a", str(tmp), str(fake))
    assert wait(lambda: (t.window(wid) or {}).get("cmd") == "claude")
    assert not t.window(wid).get("sleep")


def test_panel_shows_sleep_status():
    page = (Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html").read_text()
    assert 'sleep: { label: "💤 спит"' in page
    src = (Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "webapp.py").read_text()
    assert '"status": "sleep" if w.get("sleep")' in src
