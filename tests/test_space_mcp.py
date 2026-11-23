"""Свои интеграции пространства (GAS-38 (в), space_mcp.py): у каждого пространства свои ключи и подключения.

Настоящие серверы tmux по коротким сокетам (фикстура ``world`` из tests/test_tenant_testers.py): пространства без
sudo, команды в пространстве — ``tmux run-shell`` его сервера. Проверяем: тестировщик видит и меняет только своё
(чужое пространство и интеграции владельца — нет); ключ — в файлах пространства (0600), но не в ответах API, не в
журнале событий и не в строке команды; наблюдатель не подключает; владелец видит только названия и своих интеграций
не теряет; опасные знаки в имени и в значениях не исполняются.
"""

import json
import os
import stat

import pytest
from test_tenant_testers import MEMBER, OWNER, TESTER, call, world  # noqa: F401

from gas_pult import mcp, space_mcp, space_sessions

VIEWER, OTHER_T = 7104, 7105
KEY = "github_pat_FAKE0000TEST1111NOTREAL"          # заведомо ненастоящий ключ
SKEY = "FAKE-search-key-not-real-0000"


def cj(w, slug):
    f = w["root"] / slug / "config/claude/.claude.json"
    return json.loads(f.read_text()) if f.exists() else {}


def person(w, uid, role, tenant):
    p = w["p"]
    p.people.add(uid, role, "Ещё", tenant=tenant)
    p.people.accept(uid)
    p.people.set_country(uid, chosen="NL")
    w["tok"][uid] = p.auth.issue(uid)


def seed_other(w):
    f = w["root"] / "other/config/claude/.claude.json"
    f.write_text(json.dumps({"mcpServers": {"other-crm": {"type": "http", "url": "https://crm.example/mcp",
                                                           "headers": {"Authorization": "Bearer OTHER-FAKE"}}}}))
    return f


def no_owner_cli(monkeypatch):
    """Интеграции владельца — ``claude mcp`` его папки: из панели пространства они не вызываются."""
    calls = []
    monkeypatch.setattr(mcp, "_claude", lambda *a, **k: calls.append(a) or None)
    return calls


@pytest.fixture(autouse=True)
def agree(request):
    """Согласие тестировщика на подключения (consents.py) — заранее; без него — test_space_add_needs_consent."""
    if "world" not in request.fixturenames or "needs_consent" in request.node.name:
        return
    w = request.getfixturevalue("world")
    for what in ("mcp:github", "mcp:websearch", "mcp:http"):
        assert call(w, "/api/consent", {"what": what, "accepted": True})[0] == 200


def test_space_add_needs_consent(world, monkeypatch):  # noqa: F811
    w, _ = world, no_owner_cli(monkeypatch)
    code, d = call(w, "/api/space/mcp/add", {"preset": "github", "name": "github", "values": {"token": KEY}})
    assert code == 409 and d["code"] == "consent" and d["what"] == "mcp:github" and KEY not in json.dumps(d)
    assert not cj(w, "demo").get("mcpServers")                       # без согласия ничего не записано
    assert call(w, "/api/consent", {"what": "mcp:github"})[0] == 400   # без галочки — нет
    assert call(w, "/api/consent", {"what": "mcp:github", "accepted": True})[0] == 200
    assert call(w, "/api/space/mcp/add", {"preset": "github", "name": "github", "values": {"token": KEY}})[0] == 200


def test_tester_adds_lists_removes_own_key_not_in_answers(world, monkeypatch):  # noqa: F811
    w, calls = world, no_owner_cli(monkeypatch)
    seen = []
    real_sh = space_sessions.sh
    monkeypatch.setattr(space_sessions, "sh", lambda slug, script, timeout=30: seen.append(script)
                        or real_sh(slug, script, timeout))
    code, d = call(w, "/api/space/mcp")
    assert code == 200 and d["servers"] == [] and d["space"] == "demo"
    ids = {p["id"] for p in d["presets"]}
    assert {"github", "linear", "websearch", "http"} <= ids and not ids & {"stdio", "drive", "docs", "gdrive"}
    code, d = call(w, "/api/space/mcp/add", {"preset": "github", "name": "github", "values": {"token": KEY}})
    assert code == 200, d
    assert KEY not in json.dumps(d) and [x["name"] for x in d["servers"]] == ["github"]
    assert d["servers"][0]["target"] == "https://api.githubcopilot.com"
    # ключ — у пространства, в его .claude.json (0600), как у claude mcp add-json
    assert cj(w, "demo")["mcpServers"]["github"]["headers"]["Authorization"] == "Bearer " + KEY
    assert stat.S_IMODE(os.stat(w["root"] / "demo/config/claude/.claude.json").st_mode) == 0o600
    assert not any(KEY in s for s in seen)                        # не в строке команды (видна в списке процессов)
    code, d = call(w, "/api/space/mcp")
    assert code == 200 and KEY not in json.dumps(d)
    ev = w["p"].cfg.data / "chat-events.jsonl"
    assert not ev.exists() or KEY not in ev.read_text()
    code, d = call(w, "/api/space/mcp/remove", {"name": "github"})
    assert code == 200 and d["servers"] == [] and "github" not in cj(w, "demo").get("mcpServers", {})
    assert calls == []                                            # owner's claude mcp — не трогали


def test_websearch_key_file_0600_not_in_config(world, monkeypatch):  # noqa: F811
    w = world
    no_owner_cli(monkeypatch)
    code, d = call(w, "/api/space/mcp/add", {"preset": "websearch", "name": "websearch",
                                             "values": {"engine": "brave", "token": SKEY}})
    assert code == 200, d
    kf = w["root"] / "demo/config/mcp/websearch.key"
    assert kf.read_text().strip() == SKEY and stat.S_IMODE(kf.stat().st_mode) == 0o600
    assert (w["root"] / "demo/config/mcp/base_mcp.py").is_file()
    rec = cj(w, "demo")["mcpServers"]["websearch"]
    assert SKEY not in json.dumps(rec) and rec["env"]["GAS_SEARCH_KEY_FILE"] == str(kf)
    assert SKEY not in json.dumps(d)
    assert call(w, "/api/space/mcp/remove", {"name": "websearch"})[0] == 200
    assert not kf.exists()


def test_other_space_and_owner_not_visible(world, monkeypatch):  # noqa: F811
    w = world
    calls = no_owner_cli(monkeypatch)
    f = seed_other(w)
    before = f.read_text()
    code, d = call(w, "/api/space/mcp?space=other")                # чужое пространство из запроса — не берётся
    assert code == 200 and d["space"] == "demo" and "other-crm" not in json.dumps(d)
    code, d = call(w, "/api/space/mcp/remove", {"name": "other-crm", "space": "other"})
    assert code == 400 and f.read_text() == before
    code, _ = call(w, "/api/space/mcp/add", {"preset": "github", "name": "x1", "space": "other",
                                             "values": {"token": KEY}})
    assert code == 200 and "x1" not in json.loads(f.read_text())["mcpServers"] and "x1" in cj(w, "demo")["mcpServers"]
    # интеграции владельца пространству закрыты
    assert call(w, "/api/mcp")[1].get("code") == "space"
    assert call(w, "/api/mcp/add", {"preset": "github", "name": "gh", "values": {"token": KEY}})[0] == 403
    assert call(w, "/api/mcp/remove", {"name": "github"})[0] == 403
    # тестировщик пространства other видит своё, не demo
    person(w, OTHER_T, "member", "other")
    code, d = call(w, "/api/space/mcp", who=OTHER_T)
    assert code == 200 and [x["name"] for x in d["servers"]] == ["other-crm"] and "OTHER-FAKE" not in json.dumps(d)
    assert calls == []


def test_viewer_cannot_add_member_has_no_space(world, monkeypatch):  # noqa: F811
    w = world
    no_owner_cli(monkeypatch)
    person(w, VIEWER, "viewer", "demo")
    assert call(w, "/api/space/mcp", who=VIEWER)[0] == 200
    assert call(w, "/api/space/mcp/add", {"preset": "github", "name": "github", "values": {"token": KEY}},
                who=VIEWER)[0] == 403
    assert call(w, "/api/space/mcp/remove", {"name": "github"}, who=VIEWER)[0] == 403
    assert "github" not in cj(w, "demo").get("mcpServers", {})
    assert call(w, "/api/space/mcp", who=MEMBER)[0] == 400       # не тестировщик — пространства нет


def test_owner_sees_names_only_and_keeps_own(world, monkeypatch):  # noqa: F811
    w = world
    calls = no_owner_cli(monkeypatch)
    assert call(w, "/api/space/mcp/add", {"preset": "github", "name": "github", "values": {"token": KEY}})[0] == 200
    code, d = call(w, "/api/space/mcp?space=demo", who=OWNER)
    assert code == 200 and [x["name"] for x in d["servers"]] == ["github"] and d["presets"] == []
    assert KEY not in json.dumps(d)
    # владелец из панели пространство не меняет (у него pult-tenant), и его интеграции — не затронуты
    assert call(w, "/api/space/mcp/add", {"preset": "github", "name": "g2", "space": "demo",
                                          "values": {"token": KEY}}, who=OWNER)[0] == 400
    assert call(w, "/api/space/mcp/remove", {"name": "github", "space": "demo"}, who=OWNER)[0] == 400
    assert "github" in cj(w, "demo")["mcpServers"] and calls == []


def test_reserved_and_dangerous_names_not_executed(world, monkeypatch, tmp_path):  # noqa: F811
    w = world
    no_owner_cli(monkeypatch)
    (w["root"] / "demo/config/claude/.claude.json").write_text(json.dumps(
        {"mcpServers": {"browser-local": {"type": "stdio", "command": "/usr/bin/python3"}}, "other": 1}))
    pwn = tmp_path / "pwned"
    for name in ("a; rm -rf ~", f"x$(touch {pwn})", "browser-local", "../x"):
        code, _ = call(w, "/api/space/mcp/add", {"preset": "github", "name": name, "values": {"token": KEY}})
        assert code == 400
    assert call(w, "/api/space/mcp/remove", {"name": "browser-local"})[0] == 400
    assert call(w, "/api/space/mcp/remove", {"name": "a; rm -rf ~"})[0] == 400
    # значения с командной подстановкой — только данные (через буфер tmux, не через оболочку)
    bad = f"'; touch {pwn}; echo '$(touch {pwn})`touch {pwn}`"
    code, d = call(w, "/api/space/mcp/add", {"preset": "http", "name": "crm",
                                             "values": {"url": "https://crm.example/mcp", "token": bad}})
    assert code == 200, d
    assert not pwn.exists() and (w["root"] / "demo/home").is_dir()
    got = cj(w, "demo")
    assert got["mcpServers"]["crm"]["headers"]["Authorization"] == "Bearer " + bad
    assert got["other"] == 1 and "browser-local" in got["mcpServers"]       # чужие поля .claude.json — на месте
    names = {x["name"]: x for x in call(w, "/api/space/mcp")[1]["servers"]}
    assert names["browser-local"]["removable"] is False and names["crm"]["target"] == "https://crm.example"


def test_url_with_key_cut_to_service():
    rows = space_mcp.public([{"name": "x", "type": "http", "url": "https://h.example/mcp?api_key=SECRET"}])
    assert rows == [{"name": "x", "type": "http", "target": "https://h.example", "removable": True}]
