"""Роли интерфейса (personas.py): формула возможностей, хранение вида у человека, потолок для сотрудников и проверка
потолка сервером; простой режим (#80) следует за ролью."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import personas, webapp, webauth
from gas_pult.config import Config
from gas_pult.people import People
from gas_pult.personas import ALL, CAPS, PERSONAS, Team, effective


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()


# ---------- формула ----------
def test_formula():
    bo = set(PERSONAS["business_owner"]["caps"])
    assert effective("business_owner", [], [], ALL) == bo
    # (пресет ∪ добавленные) − скрытые
    assert effective("business_owner", ["cap.pm_tasks_deadlines"], ["cap.scenarios_try"], ALL) == \
        bo - {"cap.scenarios_try"} | {"cap.pm_tasks_deadlines"}
    # скрытое побеждает добавленное
    assert "cap.dev_terminal" not in effective("developer", ["cap.dev_terminal"], ["cap.dev_terminal"], ALL)
    # ∩ потолок
    assert effective("developer", [], [], {"cap.dev_sessions", "cap.four_tabs"}) == {"cap.dev_sessions"}
    assert effective("business_owner", ["cap.dev_terminal"], [], bo) == bo
    # мусор отбрасывается, неизвестная роль — разработчик (прежний интерфейс)
    assert effective("x", ["cap.nope", 5], None, ALL) == set(PERSONAS["developer"]["caps"])
    assert effective("student", "cap.four_tabs", [], ALL) == set(PERSONAS["student"]["caps"])


def test_presets_and_catalog():
    assert set(PERSONAS) == {"business_owner", "point_admin", "project_manager", "student", "developer"}
    assert len(CAPS) == 11 and all(set(p["caps"]) <= ALL for p in PERSONAS.values())
    # простой режим из #80 — бизнес-роли и студент; разработчик — прежний интерфейс
    assert {p for p in PERSONAS if personas.simple(personas.preset(p))} == {"business_owner", "point_admin",
                                                                             "student", "project_manager"}
    assert set(personas.SIMPLE) <= {p for p in PERSONAS if personas.simple(personas.preset(p))}
    assert not personas.simple(personas.preset("developer"))
    for lang in ("ru", "en"):
        c = personas.catalog(lang)
        assert [x["id"] for x in c["caps"]] == list(CAPS) and all(x["title"] for x in c["caps"] + c["personas"])
        assert [x["id"] for x in c["sections"]] == ["search", "analytics", "docs", "comms"]
    # у каждого пути API — известная возможность
    assert set(personas.PATH_CAP.values()) <= ALL


def test_change_and_ceiling(tmp_path):
    team = Team(tmp_path / "team.json")
    rec = personas.change({}, "owner", team, 1, "business_owner")
    assert rec == {"persona": "business_owner", "onboarded": True, "added": [], "hidden": []}
    rec = personas.change(rec, "owner", team, 1, add={"cap.pm_tasks_deadlines": True, "cap.scenarios_try": False})
    assert rec["added"] == ["cap.pm_tasks_deadlines"] and rec["hidden"] == ["cap.scenarios_try"]
    rec = personas.change(rec, "owner", team, 1, add={"cap.scenarios_try": True})
    assert rec["hidden"] == [] and rec["added"] == ["cap.pm_tasks_deadlines"]     # в пресете — не храним
    # смена роли целиком — добавления и скрытия с нуля
    assert personas.change(rec, "owner", team, 1, "developer")["added"] == []
    with pytest.raises(ValueError):
        personas.change({}, "owner", team, 1, "boss")
    with pytest.raises(ValueError):
        personas.change({}, "owner", team, 1, add={"cap.nope": True})
    # сотрудник: пока владелец ничего не задал — всё (как было до ролей)
    assert personas.ceiling("staff", team, 2) == set(ALL)
    team.set(["cap.four_tabs", "cap.approvals_yes_no", "cap.assistant_guide"], ["docs", "comms"])
    assert personas.ceiling("staff", team, 2) == {"cap.four_tabs", "cap.approvals_yes_no", "cap.assistant_guide"}
    with pytest.raises(PermissionError):
        personas.change({}, "staff", team, 2, add={"cap.dev_terminal": True})
    v = personas.view({"persona": "developer"}, "staff", team, 2)
    assert v["simple"] is True and v["caps"] == ["cap.approvals_yes_no", "cap.assistant_guide"]
    assert v["sections"] == ["docs", "comms"] and v["can_team"] is False
    # поправка на конкретного человека — поверх общей политики; сброс — снова общая
    team.set(["cap.dev_sessions"], ["search"], uid=2)
    assert personas.ceiling("staff", team, 2) == {"cap.dev_sessions"} and team.sections(2) == ["search"]
    assert personas.ceiling("staff", team, 3) == {"cap.four_tabs", "cap.approvals_yes_no", "cap.assistant_guide"}
    team.set(uid=2, reset=True)
    assert team.sections(2) == ["docs", "comms"]
    with pytest.raises(ValueError):
        team.set(["cap.nope"])
    assert (tmp_path / "team.json").stat().st_mode & 0o777 == 0o600
    # гость и чужой
    assert "cap.dev_models_mcp" not in personas.ceiling("guest", team, 3)
    assert personas.ceiling(None, team, 4) == set()
    assert personas.view({}, "owner", team, 1)["ceiling"] == sorted(ALL)


def test_ui_stored_per_person(tmp_path):
    p = People(tmp_path / "people.json", [1])
    assert p.ui(1) == {} and p.ui("x") == {}
    p.set_ui(1, {"persona": "student", "onboarded": True, "junk": 1})
    assert p.ui(1)["persona"] == "student" and "junk" not in p.ui(1)
    assert (tmp_path / "ui.json").stat().st_mode & 0o777 == 0o600                    # владелец — рядом, 0600
    p.add(2, "member", "Иван")
    p.set_ui(2, {"persona": "point_admin"})
    assert json.loads((tmp_path / "people.json").read_text())["2"]["ui"]["persona"] == "point_admin"
    p.add(2, "viewer", "Иван")                                 # смена прав вид не сбрасывает
    assert p.ui(2)["persona"] == "point_admin"
    p.remove(2)
    assert p.ui(2) == {}


# ---------- сервер ----------
@pytest.fixture
def server(monkeypatch):
    panel = webapp.Panel(Config(token="1:T", owners=[1], region="NL"))
    panel.people.add(2, "member", "Иван")
    panel.people.add(3, "viewer", "Анна")
    for uid in (1, 2, 3):
        panel.people.accept(uid)
        panel.people.set_country(uid, chosen="NL")
    monkeypatch.setattr(panel, "window", lambda wid: {"id": wid, "name": "x", "path": "/tmp/x", "profile": "claude"}
                        if wid == "@1" else None)
    monkeypatch.setattr(panel.tmux, "screen", lambda wid, n=40: ["❯ "])
    monkeypatch.setattr(panel.tmux, "window", lambda wid: None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(base, path, body=None, token=""):
    h = {"Cookie": f"{webauth.COOKIE}={token}" if token else ""}
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, h)
    try:
        r = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        r = e
    return (r.status if hasattr(r, "status") else r.code), json.loads(r.read() or b"{}")


def test_persona_api(server):
    panel, base = server
    owner, member, viewer = panel.auth.issue(1), panel.auth.issue(2), panel.auth.issue(3)
    st, m = call(base, "/api/meta", token=owner)
    assert st == 200 and m["ui"]["persona"] == "developer" and m["ui"]["onboarded"] is False   # ещё не выбирал
    assert m["ui"]["access"] == "owner" and m["prefs"]["simple"] is False
    st, v = call(base, "/api/persona", {"persona": "business_owner"}, owner)
    assert st == 200 and v["simple"] is True and v["onboarded"] is True
    assert call(base, "/api/meta", token=owner)[1]["prefs"]["simple"] is True          # простой режим — за ролью
    st, v = call(base, "/api/persona", {"add": {"cap.dev_terminal": True}}, owner)
    assert "cap.dev_terminal" in v["caps"] and v["persona"] == "business_owner"
    # прежний переключатель «Простой режим» = смена роли целиком
    assert call(base, "/api/prefs", {"simple": False}, owner)[1]["simple"] is False
    assert call(base, "/api/persona", token=owner)[1]["persona"] == "developer"
    # и наблюдатель выбирает себе вид
    assert call(base, "/api/persona", {"persona": "student"}, viewer)[1]["access"] == "guest"
    assert call(base, "/api/persona", {"persona": "boss"}, member)[0] == 400
    assert call(base, "/api/persona", {"persona": "student"})[0] == 401


def test_team_ceiling_enforced(server):
    panel, base = server
    owner, member, viewer = panel.auth.issue(1), panel.auth.issue(2), panel.auth.issue(3)
    assert call(base, "/api/screen?w=@1", token=member)[0] == 200                   # потолок не задан — как раньше
    assert call(base, "/api/team", token=member)[0] == 403                          # «Команда» — только владельцу
    st, t = call(base, "/api/team", token=owner)
    assert st == 200 and t["staff_caps"] is None and [p["id"] for p in t["people"]] == [2]
    st, t = call(base, "/api/team", {"caps": ["cap.four_tabs", "cap.approvals_yes_no"], "sections": ["comms"]},
                 owner)
    assert st == 200 and t["people"][0]["ceiling"] == ["cap.approvals_yes_no", "cap.four_tabs"]
    st, d = call(base, "/api/screen?w=@1", token=member)
    assert st == 403 and d["code"] == "cap" and d["cap"] == "cap.dev_terminal"     # сервер, не только вид
    assert call(base, "/api/rename", {"w": "@1", "name": "y"}, member)[0] == 403
    assert call(base, "/api/screen?w=@1", token=owner)[0] == 200                    # владельцу — всё
    m = call(base, "/api/meta", token=member)[1]
    assert m["prefs"]["simple"] is True and m["ui"]["sections"] == ["comms"]        # инженерное закрыто — чат
    assert call(base, "/api/persona", {"add": {"cap.dev_terminal": True}}, member)[0] == 400
    # поправка на человека и сброс
    assert call(base, "/api/team", {"id": 2, "caps": sorted(ALL)}, owner)[1]["people"][0]["own_caps"] == sorted(ALL)
    assert call(base, "/api/screen?w=@1", token=member)[0] == 200
    assert call(base, "/api/team", {"id": 2, "reset": True}, owner)[1]["people"][0]["own_caps"] is None
    assert call(base, "/api/team", {"id": 3, "caps": []}, owner)[0] == 400           # наблюдатель — не сотрудник
    assert call(base, "/api/team", {"caps": ["cap.nope"]}, owner)[0] == 400
    assert call(base, "/api/screen?w=@1", token=viewer)[0] == 200                   # гостю экран смотреть можно
    panel.people.remove(2)
    assert panel.team.person(2) == {"caps": None, "sections": None}
