"""Журнал окна — по самому процессу Claude Code (``sessions/<pid>.json``), а не по метке или «последнему журналу
папки». Регрессия 09.11: окно «штаб» (старое, без метки) в папке, где пишут и другие окна и плановые запуски, —
панель брала «самый свежий» чужой журнал, и ответ сессии в Mini App пропадал."""

import json
import os
import subprocess

from gas_pult import tmux, transcripts

A = "6196e6c3-bf49-4dfe-a275-e0edb1234f35"
B = "9af5c3e4-3343-4bee-9c08-6b14a5c7a6d8"


def fake_proc(tmp_path, pid, claude_dir, sid):
    proc = tmp_path / "proc"
    (proc / str(pid)).mkdir(parents=True, exist_ok=True)
    (proc / str(pid) / "environ").write_bytes(f"HOME=/nowhere\0CLAUDE_CONFIG_DIR={claude_dir}\0".encode())
    (claude_dir / "sessions").mkdir(parents=True, exist_ok=True)
    (claude_dir / "sessions" / f"{pid}.json").write_text(json.dumps({"pid": pid, "sessionId": sid}))
    return proc


def test_live_sid_reads_process_session(tmp_path):
    proc = fake_proc(tmp_path, 4242, tmp_path / "claude", A)
    assert tmux.live_sid(4242, str(proc)) == A
    assert tmux.live_sid(4243, str(proc)) == ""                       # нет процесса
    (tmp_path / "claude/sessions/4242.json").write_text('{"sessionId": "../../etc"}')
    assert tmux.live_sid(4242, str(proc)) == ""                       # не uuid — не доверяем


def test_live_sid_home_fallback(tmp_path):
    proc = tmp_path / "proc"
    (proc / "7").mkdir(parents=True)
    (proc / "7" / "environ").write_bytes(f"HOME={tmp_path}\0".encode())
    (tmp_path / ".claude/sessions").mkdir(parents=True)
    (tmp_path / ".claude/sessions/7.json").write_text(json.dumps({"sessionId": B}))
    assert tmux.live_sid(7, str(proc)) == B


def test_windows_take_sid_from_process(monkeypatch, tmp_path):
    t = tmux.Tmux("main")
    line = "\t".join(["@1", "1", "штаб", "node", "/p", "/dev/pts/9", "", "", ""])     # старое окно без метки
    monkeypatch.setattr(t, "run", lambda *a: line)
    ps = subprocess.CompletedProcess([], 0, "  100 -bash\n  101 claude\n", "")
    monkeypatch.setattr(tmux.subprocess, "run", lambda *a, **k: ps)
    monkeypatch.setattr(tmux, "live_sid", lambda pid, proc="/proc": A if str(pid) == "101" else "")
    w = t.windows()[0]
    assert w["cmd"] == "claude" and w["sid"] == A and w["live"] and w["tag"] == ""


def test_untagged_window_reads_own_journal_not_newest(tmp_path):
    """Два журнала в одной папке: свежее пишет соседнее окно — окно «штаб» всё равно читает свой."""
    home = tmp_path / "claude"
    d = transcripts.project_dir("/p", home)
    d.mkdir(parents=True)
    for sid, text, mtime in ((A, "ответ про F5 и диктовку", 100), (B, "соседняя сессия", 200)):
        f = d / f"{sid}.jsonl"
        f.write_text(json.dumps({"type": "assistant", "sessionId": sid, "timestamp": "2026-11-09T13:19:02Z",
                                 "uuid": sid[:8], "message": {"role": "assistant", "content": [
                                     {"type": "text", "text": text}]}}) + "\n")
        os.utime(f, (mtime, mtime))
    assert transcripts.current("/p", home).stem == B                 # «последний в папке» — чужой (так было)
    assert transcripts.current("/p", home, sid=A).stem == A          # по id процесса — свой
    assert "F5" in transcripts.last_answer("/p", home, sid=A)
