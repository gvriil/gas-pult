"""«Проекты» (задача 49, PR 3): «Новая сессия в проекте» (ещё одно окно в той же папке, свой журнал), завершённые
чаты проекта (журналы без окна), их переписка, «Продолжить» (--resume), переименовать и скрыть. Без живого tmux и
Claude: окна и запуск подменены, домашняя папка и журналы — во временной папке."""

import contextlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import projects, transcripts, webapp, webauth
from gas_pult.config import Config

OPEN, OLD, NEW, LEG, OTHER = (str(uuid.UUID(int=i)) for i in (11, 12, 13, 14, 15))


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}, "timestamp": "2026-11-07T10:00:00Z"}


def ai(text):
    return {"type": "assistant", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]},
            "timestamp": "2026-11-07T10:00:05Z"}


def put(d, sid, entries, age):
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{sid}.jsonl"
    f.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    t = time.time() - age
    os.utime(f, (t, t))
    return f


class Wins:
    session = "main"
    scoped = None

    def __init__(self, wins):
        self.wins, self.opened = wins, []

    def windows(self):
        return [dict(w) for w in self.wins]

    def window(self, wid):
        return next((dict(w) for w in self.wins if w["id"] == wid), None)

    def screen(self, wid, n=25):
        return []

    def run(self, *a, **k):
        return ""

    def new_window(self, name, path, cmd, mark="claude", by="", sid=""):
        wid = f"@{20 + len(self.opened)}"
        self.opened.append({"name": name, "path": path, "cmd": cmd, "by": by, "sid": sid})
        self.wins.append({"id": wid, "name": name, "cmd": "claude", "mark": mark, "path": path, "by": by, "sid": sid,
                          "channel": False, "profile": mark})
        return wid

    def all_spaces(self):
        return contextlib.nullcontext()

    @contextlib.contextmanager
    def scope(self, slug):
        yield


@pytest.fixture
def server(monkeypatch, tmp_path):
    home = tmp_path / "home"
    shop = home / "projects" / "shop"
    shop.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", home / ".claude" / "projects")
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.add(2, "member", "Иван")
    p.people.add(3, "viewer", "Анна")
    for uid in (1, 2, 3):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    wins = Wins([{"id": "@1", "name": "shop-1", "cmd": "claude", "mark": "claude", "path": str(shop), "by": "",
                  "sid": OPEN, "channel": False, "profile": "claude"}])
    monkeypatch.setattr(p, "tmux", wins)
    monkeypatch.setattr(p.pult, "tmux", wins)
    monkeypatch.setattr(p, "need_claude", lambda: None)
    monkeypatch.setattr(webapp.models, "command", lambda base, profile, st, **kw: "claude")
    monkeypatch.setattr(webapp.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "main\n"})())
    d = transcripts.project_dir(str(shop))
    put(d, OPEN, [user("Открытый чат"), ai("работаю")], 5)
    put(d, OLD, [user("Цены конкурентов"), ai("вот"), user("ещё"), ai("готово про паллеты")], 86400)
    put(d, NEW, [{"type": "summary", "summary": "Описание товаров"}, user("опиши"), ai("ок")], 3600)
    put(d, str(uuid.uuid4()), [{"type": "file-history-snapshot"}], 10)          # без сообщений — не чат
    put(transcripts.project_dir(str(shop), p.cfg.data / "people/2/claude"), OTHER, [user("Чат участника")], 7200)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    pid = projects.pid_of(os.path.realpath(shop))
    yield p, f"http://127.0.0.1:{srv.server_address[1]}", wins, pid, shop
    srv.shutdown()


def call(base, path, body=None, tok=""):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={tok}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_new_session_in_project_second_window(server):
    p, base, wins, pid, shop = server
    tok = p.auth.issue(1)
    assert call(base, "/api/meta", tok=tok)[1]["projects_ui"] is True
    code, d = call(base, "/api/project/session", {"id": pid}, tok)
    assert code == 200 and d["id"] == "@20" and d["project"] == pid
    w = wins.opened[-1]
    assert w["path"] == str(shop) and w["cmd"] == f"claude --session-id {w['sid']}" and w["sid"] == d["sid"]
    ss = {x["id"]: x for x in call(base, "/api/sessions", tok=tok)[1]["sessions"]}
    assert ss["@1"]["project"] == ss["@20"]["project"] == pid                  # два окна в одной папке — один проект
    assert ss["@1"]["title"] == "Открытый чат"                                   # название чата — из журнала
    assert call(base, "/api/project/session", {"id": "pnone"}, tok)[0] == 404
    assert call(base, "/api/project/session", {"id": pid}, p.auth.issue(3))[0] == 403   # наблюдатель — не пишет
    code, d = call(base, "/api/project/session", {"id": pid}, p.auth.issue(2))         # участник — своей учёткой
    assert code == 200 and wins.opened[-1]["by"] == "2" and "--session-id" in wins.opened[-1]["cmd"]


def test_done_chats_list_search_and_history(server):
    p, base, _, pid, _ = server
    tok = p.auth.issue(1)
    code, d = call(base, f"/api/project/sessions?id={pid}", tok=tok)
    assert code == 200 and d["keep_days"] == 30
    assert [(c["sid"], c["title"], c["msgs"], c["mine"]) for c in d["chats"]] == [
        (NEW, "Описание товаров", 1, True), (OTHER, "Чат участника", 1, False), (OLD, "Цены конкурентов", 2, True)]
    assert OPEN not in json.dumps(d)                                              # открытый в окне — в «Активных»
    assert [c["sid"] for c in call(base, f"/api/project/sessions?id={pid}&q=%D1%86%D0%B5%D0%BD", tok=tok)[1]["chats"]] \
        == [OLD]                                                                  # по названию («цен»)
    assert [c["sid"] for c in call(base, f"/api/project/sessions?id={pid}&q=%D0%BF%D0%B0%D0%BB%D0%BB%D0%B5%D1%82",
                                   tok=tok)[1]["chats"]] == [OLD]                 # по тексту («паллет»)
    p.CHATS_PAGE = 2
    d = call(base, f"/api/project/sessions?id={pid}", tok=tok)[1]
    assert d["more"] and len(d["chats"]) == 2
    rest = call(base, f"/api/project/sessions?id={pid}&before={d['before']}", tok=tok)[1]
    assert [c["sid"] for c in rest["chats"]] == [OLD] and not rest["more"]
    code, h = call(base, f"/api/project/history?id={pid}&sid={OLD}", tok=p.auth.issue(3))   # наблюдатель читает
    assert code == 200 and [x["text"] for x in h["items"]] == ["Цены конкурентов", "вот", "ещё", "готово про паллеты"]
    assert call(base, f"/api/project/history?id={pid}&sid=../../x", tok=tok)[0] == 404
    assert call(base, f"/api/project/history?id={pid}&sid={uuid.uuid4()}", tok=tok)[0] == 404


def test_legacy_window_hides_latest_journal(server):
    p, base, wins, pid, _ = server
    wins.wins[0]["sid"] = ""                                    # старое окно без метки — его журнал последний в папке
    p._proj = (0.0, {})
    sids = [c["sid"] for c in call(base, f"/api/project/sessions?id={pid}", tok=p.auth.issue(1))[1]["chats"]]
    assert OPEN not in sids and NEW in sids


def test_resume_rename_hide(server):
    p, base, wins, pid, shop = server
    tok = p.auth.issue(1)
    code, d = call(base, "/api/project/resume", {"id": pid, "sid": OLD}, tok)
    assert code == 200 and wins.opened[-1]["cmd"] == f"claude --resume {OLD}" and wins.opened[-1]["sid"] == OLD
    code, again = call(base, "/api/project/resume", {"id": pid, "sid": OLD}, tok)
    assert again == {"id": d["id"], "existing": True, "sid": OLD} and len(wins.opened) == 1   # уже открыт — его окно
    code, e = call(base, "/api/project/resume", {"id": pid, "sid": OTHER}, tok)
    assert code == 400 and "другой учётке" in e["error"]  # чат участника — чужая учётка
    code, d = call(base, "/api/project/resume", {"id": pid, "sid": OTHER}, p.auth.issue(2))
    assert code == 200 and wins.opened[-1]["by"] == "2" and wins.opened[-1]["cmd"].endswith(f"--resume {OTHER}")
    assert call(base, "/api/project/chat", {"id": pid, "sid": NEW, "title": "  Тексты   карточек "}, tok)[1][
        "title"] == "Тексты карточек"
    chats = call(base, f"/api/project/sessions?id={pid}", tok=tok)[1]["chats"]
    assert chats[0]["title"] == "Тексты карточек"
    call(base, "/api/project/chat", {"id": pid, "sid": NEW, "hidden": True}, tok)
    assert NEW not in [c["sid"] for c in call(base, f"/api/project/sessions?id={pid}", tok=tok)[1]["chats"]]
    data = json.loads((p.cfg.data / "projects.json").read_text())
    assert data["sessions"][NEW] == {"project": pid, "title": "Тексты карточек", "hidden": True}
    assert (shop.parent.parent / ".claude").exists()                             # журналы на месте, ничего не удалено
    assert call(base, "/api/project/chat", {"id": pid, "sid": NEW, "title": "x"}, p.auth.issue(3))[0] == 403


def test_projects_superset_of_sessions(server):
    p, base, *_ = server
    d = call(base, "/api/projects", tok=p.auth.issue(1))[1]
    assert {"projects", "sessions", "host", "build", "cost", "fallback", "now"} <= set(d)
