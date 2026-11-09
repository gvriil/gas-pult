"""«Закрепить» проект, сессию и завершённый чат: группа наверху, порядок — по времени закрепления, хранится в
``projects.json`` (одинаково на телефоне и в браузере) и переживает перезапуск окна (по id сессии Claude Code).
Без живого tmux и Claude: окна подменены (``Wins`` из test_project_chats), журналы — во временной папке."""

import itertools
import json
import os
import time
import types

from test_project_chats import NEW, OLD, OPEN, call
from test_project_chats import server as server

from gas_pult import projects, webapp
from gas_pult.config import Config


def test_pin_project_order_and_storage(server, monkeypatch, tmp_path):
    p, base, _wins, pid, shop = server
    tok = p.auth.issue(1)
    other = shop.parent / "blog"
    other.mkdir()
    p.project_data(fresh=True)
    p.projects.sync([str(other)], [], {})
    p._proj = (0.0, {})
    ids = [x["id"] for x in call(base, "/api/projects", tok=tok)[1]["projects"]]
    blog = projects.pid_of(os.path.realpath(other))
    assert blog in ids and pid in ids
    clock = itertools.count(1000, 1000)
    monkeypatch.setattr(projects, "time", types.SimpleNamespace(time=lambda: next(clock)))
    assert call(base, "/api/pin", {"project": blog, "on": True}, tok)[1] == {"pinned": 1000}
    assert call(base, "/api/pin", {"project": pid, "on": True}, tok)[1] == {"pinned": 2000}
    monkeypatch.setattr(projects, "time", time)
    ps = call(base, "/api/projects", tok=tok)[1]["projects"]
    assert [x["id"] for x in ps[:2]] == [pid, blog]                       # последний закреплённый — первым
    assert ps[0]["pinned"] is True and ps[0]["pinned_at"] == 2000         # pinned — как было (да/нет), время — новое
    assert json.loads((p.cfg.data / "projects.json").read_text())["projects"][blog]["pinned"] == 1000
    assert call(base, "/api/pin", {"project": pid, "on": False}, tok)[1] == {"pinned": 0}
    ps = call(base, "/api/projects", tok=tok)[1]["projects"]
    assert ps[0]["id"] == blog and not next(x for x in ps if x["id"] == pid)["pinned"]
    assert call(base, "/api/pin", {"project": "pnone"}, tok)[0] == 404
    assert call(base, "/api/pin", {"project": blog, "on": False}, p.auth.issue(3))[0] == 403   # наблюдатель — нет
    assert call(base, "/api/pin", {"project": blog, "on": False}, p.auth.issue(2))[0] == 200   # участник — да


def test_pin_window_survives_restart_and_reaches_done_chat(server):
    p, base, wins, pid, shop = server
    tok = p.auth.issue(1)
    wins.wins.append({"id": "@2", "name": "shop-2", "cmd": "claude", "mark": "claude", "path": str(shop), "by": "",
                      "sid": "", "channel": False, "profile": "claude"})          # старое окно без метки — по папке
    code, d = call(base, "/api/pin", {"w": "@1"}, tok)
    assert code == 200 and d["pinned"] > 0
    ss = {x["id"]: x for x in call(base, "/api/sessions", tok=tok)[1]["sessions"]}
    assert ss["@1"]["pinned"] == d["pinned"] and ss["@2"]["pinned"] == 0
    data = json.loads((p.cfg.data / "projects.json").read_text())
    assert data["pins"] == {"sid:" + OPEN: d["pinned"]}
    # перезапуск окна с продолжением: новое окно, тот же id сессии — закрепление на месте
    wins.wins[0] = {**wins.wins[0], "id": "@7"}
    assert {x["id"]: x for x in call(base, "/api/sessions", tok=tok)[1]["sessions"]}["@7"]["pinned"] == d["pinned"]
    # и после перезапуска панели (та же папка данных)
    p2 = webapp.Panel(Config(token="1:T", owners=[1]))
    p2.tmux = p2.pult.tmux = wins
    assert {x["id"]: x for x in p2.sessions()}["@7"]["pinned"] == d["pinned"]
    assert call(base, "/api/pin", {"w": "@2"}, tok)[0] == 200
    key = "path:" + projects.tilde(os.path.realpath(shop), p.pult.home)
    assert key in json.loads((p.cfg.data / "projects.json").read_text())["pins"]
    # окна закрыли — закреплённый чат сверху «Завершённых», несмотря на возраст
    del wins.wins[:]
    p._proj = (0.0, {})
    chats = call(base, f"/api/project/sessions?id={pid}", tok=tok)[1]["chats"]
    assert chats[0]["sid"] == OPEN and chats[0]["pinned"] == d["pinned"]
    assert call(base, "/api/pin", {"w": "@99"}, tok)[0] == 404


def test_pin_done_chat_on_top_of_first_page_only(server):
    p, base, _wins, pid, _shop = server
    tok = p.auth.issue(1)
    first = [c["sid"] for c in call(base, f"/api/project/sessions?id={pid}", tok=tok)[1]["chats"]]
    assert first[-1] == OLD                                                 # самый старый — внизу
    assert call(base, "/api/pin", {"id": pid, "sid": OLD}, tok)[0] == 200
    chats = call(base, f"/api/project/sessions?id={pid}", tok=tok)[1]["chats"]
    assert chats[0]["sid"] == OLD and chats[0]["pinned"] and not chats[1]["pinned"]
    assert [c["sid"] for c in chats].count(OLD) == 1
    p.CHATS_PAGE = 1
    d = call(base, f"/api/project/sessions?id={pid}", tok=tok)[1]
    assert [c["sid"] for c in d["chats"]] == [OLD, NEW] and d["more"]
    rest = call(base, f"/api/project/sessions?id={pid}&before={d['before']}", tok=tok)[1]["chats"]
    assert OLD not in [c["sid"] for c in rest]                              # на следующих страницах — не повторяется
    q = call(base, f"/api/project/sessions?id={pid}&q=%D0%BE%D0%BF%D0%B8%D1%81", tok=tok)[1]["chats"]   # «опис»
    assert [c["sid"] for c in q] == [NEW]                                    # поиск: закреплённый не подмешивается
    assert call(base, "/api/pin", {"id": pid, "sid": OLD, "on": False}, tok)[1] == {"pinned": 0}
    p.CHATS_PAGE = 20
    assert call(base, f"/api/project/sessions?id={pid}", tok=tok)[1]["chats"][-1]["sid"] == OLD
