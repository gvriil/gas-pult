"""«Перенести в проект…» (владелец 22.11): чат продолжается в папке другого проекта с той же историей.

Без живого tmux и Claude: окна подменены (``KillWins`` из test_session_delete), журналы — во временной папке.
Проверяем: копия журнала (и папки ``<id>/``) в папку журналов новой папки, окно — там же с ``--resume <id>`` и именем
по правилу пульта, старый журнал — в корзине чатов (вернуть можно), название и закрепление — за чатом; идёт ход —
перенос откладывается и выполняется фоновым циклом; CLI; права и пространства."""

import argparse
import json
import os

import pytest
from test_project_chats import OPEN, call, put, user
from test_project_chats import server as server
from test_session_delete import KillWins

from gas_pult import chat_move, chat_trash, cli, projects, transcripts


@pytest.fixture
def mv(server, monkeypatch):
    p, base, wins, pid, shop = server
    blog = shop.parent / "blog"
    blog.mkdir()
    kw = KillWins(wins.wins)
    monkeypatch.setattr(p, "tmux", kw)
    monkeypatch.setattr(p.pult, "tmux", kw)
    quits = []

    def quit_ex(w):
        quits.append(w["id"])
        kw.kill(w["id"])
        return {"result": "closed", "draft": ""}
    monkeypatch.setattr(p.pult, "quit_ex", quit_ex)
    monkeypatch.setattr(p.pult, "activity", lambda w, screen=None: {"phase": "idle"})
    side = transcripts.project_dir(str(shop)) / OPEN / "subagents"      # журналы субагентов рядом с журналом
    side.mkdir(parents=True)
    (side / "a.jsonl").write_text("{}\n")
    p._proj = (0.0, {})
    bid = p.projects.of_path(p.project_data(fresh=True), str(blog))
    assert bid and bid != pid
    return p, base, kw, pid, bid, shop, blog, quits


def test_move_copies_journal_and_resumes_in_new_folder(mv):
    p, base, kw, pid, bid, shop, blog, quits = mv
    tok = p.auth.issue(1)
    p.projects.set_chat(OPEN, pid, title="Своё название")
    p.projects.set_pin("owner", True, key="sid:" + OPEN)
    p.pult.set_state(window_models={"@1": "opus"}, window_efforts={"@1": "high"})
    old = transcripts.project_dir(str(shop)) / f"{OPEN}.jsonl"
    before = old.read_bytes()
    code, d = call(base, "/api/chat/move", {"w": "@1", "project": bid}, tok)
    assert code == 200, d
    assert d["moved"] and d["project"] == bid and d["sid"] == OPEN and d["id"] == "@20"
    new = transcripts.project_dir(os.path.realpath(blog)) / f"{OPEN}.jsonl"
    assert new.read_bytes() == before                                    # та же история, байт в байт
    assert (new.parent / OPEN / "subagents" / "a.jsonl").is_file()        # и журналы субагентов
    assert not old.exists() and not (old.parent / OPEN).exists()          # старый — в корзине, не стёрт
    assert [x["sid"] for x in chat_trash.listing(p.cfg.data)] == [OPEN]
    assert quits == ["@1"]                                                # Claude вышел штатно
    o = kw.opened[-1]
    assert o["path"] == os.path.realpath(blog) and o["sid"] == OPEN
    assert o["cmd"].endswith(f" --resume {OPEN}") and "--model opus" in o["cmd"] and "--effort high" in o["cmd"]
    assert o["name"].startswith("blog-")                                  # имя окна — по новой папке
    st = p.pult.state()
    assert st["window_models"] == {"@20": "opus"} and st["window_efforts"] == {"@20": "high"}
    data = p.project_data(fresh=True)
    rec = data["sessions"][OPEN]
    assert rec["project"] == bid and rec["title"] == "Своё название" and not rec.get("hidden")
    ss = {x["id"]: x for x in call(base, "/api/sessions", tok=tok)[1]["sessions"]}
    assert ss["@20"]["project"] == bid and ss["@20"]["title"] == "Своё название" and ss["@20"]["pinned"]
    ev = [json.loads(x) for x in (p.cfg.data / "chat-events.jsonl").read_text().splitlines()]
    assert any(e["ev"] == "chat_move" and e["state"] == "done" and e["project"] == bid for e in ev)
    assert "Своё" not in json.dumps([e for e in ev if e["ev"] == "chat_move"])   # без текста переписки
    tid = chat_trash.listing(p.cfg.data)[0]["id"]                          # «Вернуть» — журнал снова на старом месте
    assert call(base, "/api/chat/restore", {"id": tid}, tok)[0] == 200 and old.read_bytes() == before


def test_move_refusals_change_nothing(mv):
    p, base, kw, pid, bid, shop, blog, _quits = mv
    tok = p.auth.issue(1)
    assert call(base, "/api/chat/move", {"w": "@1", "project": pid}, tok)[1]["error"] == "чат уже в этом проекте"
    assert call(base, "/api/chat/move", {"w": "@1", "project": "pnone"}, tok)[0] == 404
    assert call(base, "/api/chat/move", {"w": "@9", "project": bid}, tok)[0] == 404
    dst = transcripts.project_dir(os.path.realpath(blog))
    put(dst, OPEN, [user("чужая копия")], 5)                              # в новой папке уже есть этот id
    code, d = call(base, "/api/chat/move", {"w": "@1", "project": bid}, tok)
    assert code == 200 and "уже есть журнал" in d["failed"] and d["id"] == "@20"   # чат открыт на прежнем месте
    assert kw.opened[-1]["path"] == str(shop) and (transcripts.project_dir(str(shop)) / f"{OPEN}.jsonl").is_file()
    assert (dst / f"{OPEN}.jsonl").read_text().count("чужая копия") == 1
    assert chat_trash.listing(p.cfg.data) == []


def test_busy_window_moves_after_turn(mv, monkeypatch):
    p, base, kw, pid, bid, _shop, blog, quits = mv
    tok = p.auth.issue(1)
    phase = {"v": "working"}
    monkeypatch.setattr(p.pult, "activity", lambda w, screen=None: {"phase": phase["v"]})
    code, d = call(base, "/api/chat/move", {"w": "@1", "project": bid}, tok)
    assert code == 200 and d["pending"] and d["text"] == "Перенесу, как только закончит"
    assert quits == [] and kw.opened == []                                # ход не прерван
    assert p.move_pending("@1")["project"] == bid
    assert p.move_tick() == [] and quits == []                            # всё ещё отвечает — ждём
    phase["v"] = "done"
    assert p.move_tick() == ["@20"] and quits == ["@1"]                   # закончил — перенесли
    assert kw.opened[-1]["path"] == os.path.realpath(blog) and p.move_pending("@1") is None
    assert p.move_tick() == []                                            # второй раз не выполняется
    # отменить отложенный
    phase["v"] = "working"
    assert call(base, "/api/chat/move", {"w": "@20", "project": pid}, tok)[1]["pending"]
    assert call(base, "/api/chat/move", {"w": "@20", "cancel": True}, tok)[1] == {"cancelled": True}
    phase["v"] = "done"
    assert p.move_tick() == []


def test_pending_dropped_when_window_gone(mv, monkeypatch):
    p, _base, kw, _pid, bid, *_ = mv
    p.moves.add("@1", bid)
    kw.wins.clear()
    assert p.move_tick() == [] and p.moves.read() == {}


def test_cli_move_and_wait(mv, monkeypatch, capsys):
    p, _base, _kw, pid, _bid, shop, blog, _quits = mv
    phase = ["working", "working", "done"]
    monkeypatch.setattr(p.pult, "activity", lambda w, screen=None: {"phase": phase.pop(0) if phase else "done"})
    slept = []
    a = argparse.Namespace(action="move", window="main:shop-1", folder=str(blog), wait=True, timeout=60)
    r = cli.cmd_chat(a, panel=p, sleep=slept.append)
    assert r["id"] == "@20" and len(slept) == 2 and "blog" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="не найдено"):
        cli.cmd_chat(argparse.Namespace(action="move", window="main:нет", folder=str(blog), wait=False, timeout=1),
                     panel=p)
    with pytest.raises(SystemExit, match="не проект"):
        cli.cmd_chat(argparse.Namespace(action="move", window="@20", folder=str(shop / "nope"), wait=False,
                                        timeout=1), panel=p)
    # без --wait и занятое окно — в очередь панели
    monkeypatch.setattr(p.pult, "activity", lambda w, screen=None: {"phase": "working"})
    r = cli.cmd_chat(argparse.Namespace(action="move", window="@20", folder=str(shop), wait=False, timeout=1), panel=p)
    assert r["pending"] and p.moves.get("@20")["project"] == pid


def test_rights_and_spaces(mv):
    p, base, kw, _pid, bid, *_ = mv
    for uid in (2, 3):                                                     # участник и наблюдатель — нет
        assert call(base, "/api/chat/move", {"w": "@1", "project": bid}, p.auth.issue(uid))[0] == 403
    kw.wins.append({"id": "@5", "name": "s-1", "cmd": "claude", "mark": "claude", "path": "/srv/x", "by": "",
                    "sid": OPEN, "channel": False, "profile": "claude", "space": "demo"})
    with pytest.raises(ValueError, match="В пространстве перенос чата пока недоступен"):
        p.chat_move("@5", bid)
    kw.wins.append({"id": "@6", "name": "pi-1", "cmd": "pi", "mark": "pi", "path": str(mv[5]), "by": "",
                    "sid": OPEN, "channel": False, "profile": "pi", "stopped": True})
    with pytest.raises(ValueError, match="только чаты Claude Code"):
        p.chat_move("@6", bid)


def test_copy_journal_unit(tmp_path):
    src = tmp_path / "a"
    f = put(src, OPEN, [user("x")], 5)
    with pytest.raises(ValueError, match="уже в этой папке"):
        chat_move.copy_journal(f, src)
    out = chat_move.copy_journal(f, tmp_path / "b")
    assert out.read_bytes() == f.read_bytes() and f.exists()
    assert not list((tmp_path / "b").glob(".*part"))
    with pytest.raises(LookupError):
        chat_move.copy_journal(tmp_path / "nope.jsonl", tmp_path / "c")


def test_ui_has_move_item():
    from pathlib import Path
    web = Path(projects.__file__).with_name("web")
    html = (web / "index.html").read_text(encoding="utf-8")
    assert html.count('part("chatmove")') >= 2                            # «⋯» чата и меню строки в списке
    js = (web / "js" / "chatmove.js").read_text(encoding="utf-8")
    assert "/api/chat/move" in js and "Перенесу, как только закончит" not in js   # текст — с сервера
    assert len((web / "index.html").read_bytes()) < 770000
