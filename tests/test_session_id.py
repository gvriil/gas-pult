"""Окно ↔ свой журнал Claude Code (задача 49, PR 2; очередь HANDOFF, п. 7). Новое окно пульта запускает Claude с
``--session-id <uuid>`` и ставит метку ``@gas_pult_sid``: переписка, превью, строка статуса, расход и «Продолжить»
читают ``<uuid>.jsonl``, а не «последний журнал папки» — две сессии в одной папке больше не путаются. Старые окна
без метки — как раньше. Без живого tmux и Claude: окна и запуск подменены."""

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid

import pytest

from gas_pult import activity, transcripts, usage, webapp
from gas_pult.config import Config

A, B, C = (str(uuid.UUID(int=i)) for i in (1, 2, 3))


def put(d, sid, text, mtime, model="claude-opus-5-5"):
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{sid}.jsonl"
    f.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": f"вопрос {text}"},
                             "timestamp": "2026-11-07T10:00:00Z"}, ensure_ascii=False) + "\n" +
                 json.dumps({"type": "assistant", "message": {"model": model, "stop_reason": "end_turn",
                                                              "content": [{"type": "text", "text": f"ответ {text}"}],
                                                              "usage": {"input_tokens": 10, "output_tokens": 5}},
                             "timestamp": "2026-11-07T10:00:05Z"}, ensure_ascii=False) + "\n", encoding="utf-8")
    os.utime(f, (mtime, mtime))
    return f


@pytest.fixture
def two(tmp_path, monkeypatch):
    """Папка /p/shop с двумя журналами: A (старее) и B (новее)."""
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", tmp_path / "claude" / "projects")
    d = transcripts.project_dir("/p/shop")
    now = time.time()
    put(d, A, "первой", now - 100)
    put(d, B, "второй", now - 10)
    return d


def test_own_journal_not_the_latest(two):
    assert transcripts.current("/p/shop", sid=A).stem == A               # своя метка — свой журнал
    assert transcripts.current("/p/shop").stem == B                     # без метки — как раньше, последний
    assert transcripts.current("/p/shop", sid=C) is None                 # своего ещё нет — не чужой
    assert transcripts.current("/p/shop", sid="../../etc/passwd").stem == B   # не uuid — метки нет
    items, _ = transcripts.history("/p/shop", sid=A)
    assert [x["text"] for x in items] == ["вопрос первой", "ответ первой"]
    assert transcripts.last_answer("/p/shop", sid=A) == "ответ первой"
    assert transcripts.last_answer("/p/shop") == "ответ второй"
    assert transcripts.preview("/p/shop", sid=A) == "ответ первой"
    assert transcripts.revision("/p/shop", sid=A).startswith(A[:8])
    assert transcripts.revision("/p/shop", sid=C) == ""
    j = activity.Journal()
    assert j.status("/p/shop", sid=C) == activity.parse([]) != j.status("/p/shop", sid=A)   # строка статуса — своя
    put(two.parent / "-p-shop-sub", C, "в подпапке", time.time())       # окно сменило каталог — найдём по id
    assert transcripts.current("/p/shop", sid=C).stem == C


def test_resume_args():
    assert transcripts.resume_args(A) == f" --resume {A}"
    assert transcripts.resume_args("") == transcripts.resume_args("x; rm -rf ~") == " --continue"


def test_follow_after_clear(two):
    assert transcripts.follow("/p/shop", None, A, set()) == B           # /clear: новый ничей журнал — этого окна
    assert transcripts.follow("/p/shop", None, A, {B}) == ""            # журнал другого окна — не забираем
    assert transcripts.follow("/p/shop", None, B, set()) == ""          # своё — самое новое
    assert transcripts.follow("/p/shop", None, C, set()) == ""          # своего ещё нет — ждём первого сообщения


def test_batch_run_is_not_clear(two):
    """Плановый ``claude -p`` (``entrypoint`` = ``sdk-cli``) в той же папке — новее журнала окна, но не его /clear:
    метка не переезжает, и окно без метки его не показывает (ревью 09.11, п. 5)."""
    f = put(two, C, "плана", time.time())
    f.write_text("".join(json.dumps({**json.loads(x), "entrypoint": "sdk-cli"}) + "\n"
                         for x in f.read_text().splitlines()))
    assert transcripts.is_batch(f)
    assert transcripts.follow("/p/shop", None, B, set()) == ""
    assert transcripts.current("/p/shop").stem == B


def test_usage_by_session(two, monkeypatch):
    m = usage.Meter(transcripts.CLAUDE_PROJECTS)
    assert m.session("/p/shop", sid=A)["id"] == A
    assert m.session("/p/shop")["id"] == B
    assert m.session("/p/shop", sid=C) is None


@pytest.fixture
def panel(monkeypatch, tmp_path, two):
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    state, opened, respawned, labels = {"active": "@2"}, [], [], []
    monkeypatch.setattr(p.pult, "state", lambda: dict(state))
    monkeypatch.setattr(p.pult, "set_state", lambda **kw: state.update(kw))
    monkeypatch.setattr(p.pult, "projects", lambda: ["/p/shop"])
    monkeypatch.setattr(p.pult, "project_window", lambda path: None)
    monkeypatch.setattr(p, "need_claude", lambda: None)
    monkeypatch.setattr(p, "close", lambda w: "закрыто")
    monkeypatch.setattr(p.tmux, "new_window",
                        lambda name, path, cmd, **kw: opened.append((cmd, kw.get("sid"))) or f"@{10 + len(opened)}")
    monkeypatch.setattr(p.tmux, "respawn", lambda wid, path, cmd, mark="", sid=None: respawned.append(cmd))
    monkeypatch.setattr(p.tmux, "set_sid", lambda wid, sid: labels.append((wid, sid)))
    monkeypatch.setattr(webapp.models, "command", lambda base, profile, st, **kw: "claude")
    p.t = {"opened": opened, "respawned": respawned, "labels": labels}
    return p


def test_new_window_gets_own_session_id(panel):
    panel.new(0)
    cmd, sid = panel.t["opened"][-1]
    assert transcripts.valid_sid(sid) and cmd == f"claude --session-id {sid}"   # и метка окна — тот же id


def test_restart_and_revive_resume_own_session(panel, monkeypatch):
    w = {"id": "@1", "name": "a", "path": "/p/shop", "profile": "claude", "sid": A}
    panel.restart(w, "claude")
    assert panel.t["opened"][-1] == (f"claude --resume {A}", A)                  # тот же разговор, та же метка
    panel.restart(w, "claude", keep=False)
    cmd, sid = panel.t["opened"][-1]
    assert sid != A and cmd == f"claude --session-id {sid}"                      # чистый лист — новый журнал
    panel.restart({**w, "sid": ""}, "claude")
    assert panel.t["opened"][-1] == ("claude --continue", "")                    # старое окно — как раньше
    monkeypatch.setattr(panel.tmux, "window", lambda wid: {"id": wid, "stopped": True, "mark": "claude",
                                                           "path": "/p/shop", "sid": A})
    monkeypatch.setattr(panel.pult, "home_of", lambda w: None)
    panel.revive("@7")
    assert panel.t["respawned"][-1] == f"claude --resume {A}"


def test_follow_sid_moves_label_only_when_alone(panel):
    w = {"id": "@1", "cmd": "claude", "path": "/p/shop", "sid": A}
    other = {"id": "@2", "cmd": "claude", "path": "/p/shop", "sid": ""}
    assert panel.follow_sid(dict(w), [w, other], None) == A                     # рядом окно без метки — не трогаем
    assert panel.t["labels"] == []
    labelled = {**other, "sid": B}
    assert panel.follow_sid(dict(w), [w, labelled], None) == A                  # новее — журнал соседа
    assert panel.follow_sid(dict(w), [w], None) == B                            # один в папке: /clear → B
    assert panel.t["labels"] == [("@1", B)]


def test_bot_monitor_routes_by_session(two, monkeypatch):
    """Бот: ответ из журнала окна с меткой — от имени этого окна, а не «активного в папке»."""
    from gas_pult import bot
    p = bot.Pult.__new__(bot.Pult)
    wins = [{"id": "@1", "name": "первое", "cmd": "claude", "channel": False, "path": "/p/shop", "sid": A},
            {"id": "@2", "name": "второе", "cmd": "claude", "channel": False, "path": "/p/shop", "sid": B}]
    delivered = []
    p.tmux = type("T", (), {"windows": lambda self: wins, "screen": lambda self, wid: [], "hint": lambda s, w: ""})()
    p.state = lambda: {"notify": "all", "active": "@2"}
    p.home_of = lambda w: None
    p.after_pause = lambda: None
    p.notify_done_check = p.offer_hints = p.cost_watch = lambda *a, **k: None
    p.changes = type("Ch", (), {"look": lambda self, wid, lines: 0})()
    p.fallback = type("F", (), {"pending": {}, "seen": lambda self, wid, e: None})()
    p.deliver = lambda w, text: delivered.append((w["id"], text))
    p.BURST = 5
    calls = {"n": 0}

    def tick(_):
        calls["n"] += 1
        if calls["n"] == 1:                                  # после первого круга — дописываем в оба журнала
            for sid, t in ((A, "по первому"), (B, "по второму")):
                with open(two / f"{sid}.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"type": "assistant", "message": {"stop_reason": "end_turn", "content": [
                        {"type": "text", "text": t}]}}, ensure_ascii=False) + "\n")
            return
        raise SystemExit
    monkeypatch.setattr(bot.time, "sleep", tick)
    with pytest.raises(SystemExit):
        p.monitor()
    assert sorted(delivered) == [("@1", "по первому"), ("@2", "по второму")]


@pytest.mark.skipif(not shutil.which("tmux"), reason="нужен tmux")
def test_tmux_label_roundtrip(tmp_path, monkeypatch):
    from gas_pult.tmux import Tmux
    d = tempfile.mkdtemp(prefix="gp-", dir="/tmp")
    sock = os.path.join(d, "s")
    monkeypatch.setenv("GAS_PULT_TMUX_SOCKET", sock)
    try:
        t = Tmux("sid")
        wid = t.new_window("w", str(tmp_path), "sleep 30", sid=A)
        assert t.window(wid)["sid"] == A
        t.set_sid(wid, B)
        assert t.window(wid)["sid"] == B
        t.respawn(wid, str(tmp_path), "sleep 30")                       # без sid — метка остаётся
        assert t.window(wid)["sid"] == B
        t.set_sid(wid, "")
        assert t.window(wid)["sid"] == ""
    finally:
        subprocess.run(["tmux", "-S", sock, "kill-server"], capture_output=True)
        shutil.rmtree(d, ignore_errors=True)
