"""«Удалить» сессию и чат (задача: «сессии не удаляются ни из проекта, ни просто»).

Было: остановленную сессию (Claude вышел, в окне оболочка) «Завершить» не мог — ``/api/close`` шёл через ``win()``,
который пускает только окна с Claude, и отвечал 404 «Claude в этой сессии остановлен»; окно оставалось навсегда.
Завершённый чат снова появлялся в «Завершённых» — журнал Claude Code на диске, удалить было нельзя, только скрыть.

Стало: «Завершить» закрывает и остановленную; «Удалить» — окно закрыто, журнал — в корзину пульта
(``<данные>/trash/chats``), чат скрыт; не возвращается после обновления и перезапуска панели; «Вернуть» — обратно.
Без живого tmux и Claude: окна подменены (``Wins`` из test_project_chats), журналы — во временной папке."""

import json

import pytest
from test_project_chats import NEW, OLD, OPEN, Wins, call
from test_project_chats import server as server

from gas_pult import chat_trash, transcripts, webapp
from gas_pult.config import Config


class KillWins(Wins):
    def __init__(self, wins):
        super().__init__(wins)
        self.killed = []

    def kill(self, wid):
        self.killed.append(wid)
        self.wins = [w for w in self.wins if w["id"] != wid]

    def set_sid(self, wid, sid):
        pass


@pytest.fixture
def srv(server, monkeypatch):
    p, base, wins, pid, shop = server
    kw = KillWins(wins.wins)
    kw.wins.append({"id": "@2", "name": "shop-2", "cmd": "bash", "mark": "claude", "path": str(shop), "by": "",
                    "sid": OLD, "channel": False, "profile": "", "stopped": True})       # остановленная сессия
    kw.wins.append({"id": "@3", "name": "bash", "cmd": "bash", "mark": "", "path": str(shop), "by": "",
                    "sid": "", "channel": False, "profile": ""})                          # просто терминал владельца
    monkeypatch.setattr(p, "tmux", kw)
    monkeypatch.setattr(p.pult, "tmux", kw)
    quits = []

    def quit_ex(w):
        quits.append(w["id"])
        kw.kill(w["id"])
        return {"result": "closed", "draft": ""}
    monkeypatch.setattr(p.pult, "quit_ex", quit_ex)
    p._proj = (0.0, {})
    return p, base, kw, pid, shop, quits


def done(base, pid, tok):
    return [c["sid"] for c in call(base, f"/api/project/sessions?id={pid}", tok=tok)[1]["chats"]]


def test_close_stopped_session(srv):
    p, base, kw, _pid, _shop, quits = srv
    tok = p.auth.issue(1)
    code, d = call(base, "/api/close", {"w": "@2"}, tok)
    assert code == 200 and d == {"result": "закрыто", "draft": ""}            # было: 404 «Claude … остановлен»
    assert kw.killed == ["@2"] and quits == []                                # в оболочку «/exit» не печатаем
    assert call(base, "/api/close", {"w": "@3"}, tok)[0] == 404               # обычный терминал — не сессия пульта
    assert "@3" not in kw.killed


def test_delete_window_moves_journal_to_trash_and_back(srv):
    p, base, kw, pid, shop, quits = srv
    tok = p.auth.issue(1)
    f = transcripts.project_dir(str(shop)) / f"{OPEN}.jsonl"
    code, d = call(base, "/api/chat/delete", {"w": "@1"}, tok)
    assert code == 200 and d["result"] == "удалено" and d["closed"] and quits == ["@1"]
    assert d["trash"]["sid"] == OPEN and d["trash"]["title"] == "Открытый чат" and "src" not in d["trash"]
    assert not f.exists() and (p.cfg.data / "trash" / "chats" / d["trash"]["id"] / f.name).exists()
    assert OPEN not in done(base, pid, tok)                                   # не вернулся в «Завершённые»
    assert json.loads((p.cfg.data / "projects.json").read_text())["sessions"][OPEN]["hidden"] is True
    # перезапуск панели: та же папка данных — чат по-прежнему не виден, корзина на месте
    p2 = webapp.Panel(Config(token="1:T", owners=[1]))
    p2.tmux = p2.pult.tmux = kw
    assert OPEN not in [c["sid"] for c in p2.project_chats(pid)["chats"]]
    tr = call(base, "/api/chat/trash", tok=tok)[1]
    assert [x["sid"] for x in tr["trash"]] == [OPEN] and tr["trash"][0]["project_name"] == "shop"
    code, _r = call(base, "/api/chat/restore", {"id": d["trash"]["id"]}, tok)
    assert code == 200 and f.exists() and OPEN in done(base, pid, tok)        # «Вернуть» — снова в «Завершённых»
    assert call(base, "/api/chat/trash", tok=tok)[1]["trash"] == []


def test_delete_done_chat_and_stopped(srv):
    p, base, kw, pid, _shop, quits = srv
    tok = p.auth.issue(1)
    chats = {x["id"]: x for x in call(base, "/api/projects", tok=tok)[1]["projects"]}[pid]["chats"]
    code, d = call(base, "/api/chat/delete", {"id": pid, "sid": NEW}, tok)
    assert code == 200 and not d["closed"] and d["trash"]["title"] == "Описание товаров"
    assert NEW not in done(base, pid, tok)
    code, d = call(base, "/api/chat/delete", {"w": "@2"}, tok)                # остановленная: окно и её журнал
    assert code == 200 and kw.killed == ["@2"] and quits == [] and d["trash"]["sid"] == OLD
    call(base, "/api/project/chat", {"id": pid, "sid": OPEN, "hidden": True}, tok)
    ps = {x["id"]: x for x in call(base, "/api/projects", tok=tok)[1]["projects"]}
    assert ps[pid]["chats"] == chats - 3                                      # удалённые и скрытые — не в счёт
    hid = call(base, "/api/chat/trash", tok=tok)[1]["hidden"]
    assert [(x["sid"], x["title"]) for x in hid] == [(OPEN, "Открытый чат")]   # скрытый — в «Корзине», можно показать
    assert call(base, "/api/chat/delete", {"id": pid, "sid": NEW}, tok)[0] == 404   # уже в корзине


def test_delete_rights_and_refusals(srv, monkeypatch):
    p, base, kw, _pid, shop, _quits = srv
    for uid in (2, 3):                                                        # участник и наблюдатель — нет
        assert call(base, "/api/chat/delete", {"w": "@1"}, p.auth.issue(uid))[0] == 403
        assert call(base, "/api/chat/trash", tok=p.auth.issue(uid))[0] == 403
    tok = p.auth.issue(1)
    f = transcripts.project_dir(str(shop)) / f"{OPEN}.jsonl"
    monkeypatch.setattr(p.pult, "quit_ex", lambda w: {"result": "background", "draft": ""})
    code, e = call(base, "/api/chat/delete", {"w": "@1"}, tok)
    assert code == 409 and e["code"] == "force" and "фоновые задачи" in e["error"] and f.exists()   # не тронуто
    monkeypatch.setattr(p.pult, "quit_ex", lambda w: {"result": "busy", "draft": "черновик"})
    code, d = call(base, "/api/chat/delete", {"w": "@1"}, tok)                 # не вышел за 20 с — окно закрыто
    assert code == 200 and "@1" in kw.killed and d["draft"] == "черновик" and not f.exists()
    assert call(base, "/api/chat/restore", {"id": "../../etc"}, tok)[0] == 404


def test_legacy_window_with_neighbour_keeps_journals(srv):
    p, base, kw, _pid, shop, _quits = srv
    kw.wins[0]["sid"] = ""                                    # старое окно без метки, рядом в той же папке — @2
    code, d = call(base, "/api/chat/delete", {"w": "@1"}, p.auth.issue(1))
    assert code == 200 and d["closed"] and d["trash"] is None                 # окно закрыто, чужой журнал не унесли
    assert (transcripts.project_dir(str(shop)) / f"{OPEN}.jsonl").exists()


def test_trash_restore_does_not_overwrite(tmp_path):
    d = tmp_path / "j"
    d.mkdir()
    f = d / f"{OPEN}.jsonl"
    f.write_text("{}\n")
    (d / OPEN).mkdir()
    (d / OPEN / "sub.jsonl").write_text("{}\n")                # папка субагентов рядом — тоже в корзину
    rec = chat_trash.put(tmp_path / "data", f, "Чат", "p1")
    assert not f.exists() and not (d / OPEN).exists()
    f.write_text("новый\n")                                     # на прежнем месте появился журнал с тем же id
    with pytest.raises(ValueError):
        chat_trash.restore(tmp_path / "data", rec["id"])
    f.unlink()
    chat_trash.restore(tmp_path / "data", rec["id"])
    assert f.read_text() == "{}\n" and (d / OPEN / "sub.jsonl").exists() and chat_trash.listing(tmp_path / "data") == []
