"""Жизненный цикл сессии (#179 P1): закрытое не возвращается, удалить можно всегда.

Было: «Удалить» уходил на сервер через 5 с (закрыли панель — не ушёл, сессия «возвращалась»); фоновые задачи —
отказ без выхода; окна, открытые вручную, пульт метил своими и после выхода Claude они навсегда висели
«остановленными»; удалённая сессия с расписанием снова открывалась по расписанию.
Стало: запрос — сразу, «Отменить» — из корзины; «Закрыть/Удалить принудительно» (409 ``code: force``); чужие
окна не метим; «Убрать все остановленные»; при удалении расписание — на паузу."""

from pathlib import Path

from test_project_chats import call
from test_project_chats import server as server
from test_session_delete import srv as srv

from gas_pult import transcripts, webapp

INDEX = (Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html").read_text(encoding="utf-8")


def test_delete_force_after_background_refusal(srv, monkeypatch):
    p, base, kw, _pid, shop, _q = srv
    tok = p.auth.issue(1)
    f = transcripts.project_dir(str(shop)) / f"{p.tmux.window('@1')['sid']}.jsonl"
    monkeypatch.setattr(p.pult, "quit_ex", lambda w: {"result": "background", "draft": ""})
    code, e = call(base, "/api/chat/delete", {"w": "@1"}, tok)
    assert code == 409 and e["code"] == "force" and f.exists() and "@1" not in kw.killed
    code, d = call(base, "/api/chat/delete", {"w": "@1", "force": True}, tok)
    assert code == 200 and "@1" in kw.killed and d["trash"] and not f.exists()
    assert call(base, "/api/chat/restore", {"id": d["trash"]["id"]}, tok)[0] == 200   # «Отменить» — вернуть
    assert f.exists()


def test_close_force(srv, monkeypatch):
    p, base, kw, *_ = srv
    tok = p.auth.issue(1)
    monkeypatch.setattr(p.pult, "quit_ex", lambda w: {"result": "background", "draft": "черн"})
    code, d = call(base, "/api/close", {"w": "@1"}, tok)
    assert code == 200 and d["code"] == "background" and "принудительно" in d["result"] and "@1" not in kw.killed
    code, d = call(base, "/api/close", {"w": "@1", "force": True}, tok)
    assert d == {"result": "закрыто", "draft": "черн", "forced": True} and "@1" in kw.killed


def test_clear_stopped_closes_only_stopped_pult_windows(srv):
    p, base, kw, *_ = srv
    kw.wins.append({"id": "@9", "name": "space", "cmd": "bash", "mark": "claude", "path": "/x", "sid": "",
                    "stopped": True, "space": "demo"})
    tok = p.auth.issue(1)
    assert call(base, "/api/stopped/clear", {}, p.auth.issue(2))[0] == 403      # участнику — нет
    code, d = call(base, "/api/stopped/clear", {}, tok)
    assert code == 200 and d["closed"] == 1 and kw.killed == ["@2"]           # @1 живая, @3 терминал, @9 пространство


def test_unmarked_window_is_not_marked(srv, monkeypatch):
    p, *_ = srv
    runs = []
    monkeypatch.setattr(p.tmux, "run", lambda *a: runs.append(a) or "", raising=False)
    monkeypatch.setattr(p.tmux, "screen", lambda wid, n=25: ["❯ "], raising=False)
    p.tmux.wins.append({"id": "@7", "name": "руками", "cmd": "claude", "mark": "", "path": "/tmp", "sid": "",
                        "channel": False, "profile": "claude"})
    p.sessions()
    assert not [r for r in runs if "@gas_pult" in r]                       # чужое окно — без метки пульта


def test_delete_pauses_schedule(srv, monkeypatch):
    p, base, _kw, *_ = srv
    state = {"s": "on"}
    monkeypatch.setattr(p, "schedule_of", lambda path: {"state": state["s"]})
    monkeypatch.setattr(webapp.modules, "set_schedule", lambda path, st: state.update(s=st))
    code, d = call(base, "/api/chat/delete", {"w": "@1"}, p.auth.issue(1))
    assert code == 200 and state["s"] == "paused" and d["schedule"] == "paused"


def test_ui_deletes_right_away_and_offers_force():
    i = INDEX.index("async function chatDelete")
    body = INDEX[i:INDEX.index("\n}\n", i)]
    assert body.index('api("/api/chat/delete"') < body.index("undoBar(")     # запрос — до плашки, не через 5 с
    assert "chatUndo(d.trash" in body and "/api/project/resume" in INDEX   # «Отменить» — из корзины и снова открыть
    assert 'e.code === "force"' in body and "Удалить принудительно" in body
    assert "Закрыть принудительно" in INDEX and "/api/stopped/clear" in INDEX
    nav = INDEX[INDEX.index("const s = sessions.find((x) => x.id === row.dataset.nw)"):]
    nav = nav[:nav.index("function navProject")]
    assert "moduleDelete(s)" in nav and 'T("ss.del.item")' in nav           # «Удалить» и у расписания, и у пространства
