"""Тестировщик демо-пространства (задача 31): человек, привязанный к пространству, видит и трогает только его.

Настоящие серверы tmux по коротким сокетам: у «владельца» и у двух пространств (demo, other) — свои. Пространства без
sudo: ``tenants.tmux_of`` подменён на tmux по сокету, ``ready`` — да, команда запуска — поддельный «claude».
Проверяем: список сессий, экран, переписка, отправка, строка статуса, клавиши — с окнами владельца и чужого
пространства не работают (404 «окна нет»); новая сессия — в его пространстве; папки, модули, файлы, интеграции,
люди, ключи — 403 code=space; вид панели — роль пространства; функция выключена — ничего не видно и не открывается.
"""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import bot, people, spaces, tenants, webapp, webauth
from gas_pult.config import Config
from gas_pult.tmux import Tmux

pytestmark = pytest.mark.skipif(not shutil.which("tmux"), reason="нужен tmux")
OWNER, TESTER, MEMBER = 7101, 7102, 7103


def wait(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


@pytest.fixture
def world(tmp_path, monkeypatch):
    d = tempfile.mkdtemp(prefix="gp-", dir="/tmp")
    socks = {k: os.path.join(d, k[0]) for k in ("owner", "demo", "other")}
    monkeypatch.setenv("GAS_PULT_TMUX_SOCKET", socks["owner"])
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    root = tmp_path / "tenants"
    monkeypatch.setenv("GAS_PULT_TENANTS_ROOT", str(root))
    root.mkdir()
    (root / tenants.MARKER).write_text("{}")
    for slug, title in (("demo", "Демо для кафе"), ("other", "Чужое")):
        (root / slug / "home").mkdir(parents=True)
        (root / slug / "config/claude/projects").mkdir(parents=True)
        (root / slug / tenants.META).write_text(json.dumps({"title": title, "persona": "point_admin"}))
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text("#!/usr/bin/env bash\nwhile true; do printf '❯ '; read -r line; echo \"got: $line\"; done\n")
    fake.chmod(0o755)
    monkeypatch.setattr(tenants, "tmux_of", lambda slug, session="main", base_root=None:
                        Tmux("main", socket=socks[slug], home=str(root / slug / "home")))
    monkeypatch.setattr(tenants, "ready", lambda slug, base_root=None, runner=None, now=None: True)
    monkeypatch.setattr(tenants, "command", lambda t, base="claude", base_root=None: str(fake))
    p = webapp.Panel(Config(token="1:T", owners=[OWNER], region="NL", claude=str(fake), session="test",
                            project_roots=[str(tmp_path / "projects")]))
    p.people.add(TESTER, "member", "Тестировщик", tenant="demo")
    p.people.add(MEMBER, "member", "Сотрудник")
    for uid in (OWNER, TESTER, MEMBER):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    (tmp_path / "projects" / "secret").mkdir(parents=True)
    own = Tmux("test")                                       # окно владельца
    owner_w = own.new_window("owner-secret", str(tmp_path / "projects" / "secret"), str(fake))
    other_w = tenants.tmux_of("other").new_window("other-1", str(root / "other" / "home"), str(fake))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    assert wait(lambda: any(w["cmd"] == "claude" for w in own.windows()))
    yield {"p": p, "base": base, "own": own, "owner_w": owner_w, "own_n": len(own.windows()),
           "other_w": spaces.wid_of("other", other_w),
           "tok": {u: p.auth.issue(u) for u in (OWNER, TESTER, MEMBER)}, "root": root, "socks": socks}
    srv.shutdown()
    for s in socks.values():
        subprocess.run(["tmux", "-S", s, "kill-server"], capture_output=True)
    shutil.rmtree(d, ignore_errors=True)


def call(w, path, body=None, who=TESTER):
    req = urllib.request.Request(w["base"] + path, json.dumps(body).encode() if body is not None else None,
                                 {"Cookie": f"{webauth.COOKIE}={w['tok'][who]}"})
    try:
        r = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        r = e
    raw = r.read()
    try:
        return r.status if hasattr(r, "status") else r.code, json.loads(raw or b"{}")
    except ValueError:
        return r.status if hasattr(r, "status") else r.code, {"raw": len(raw)}


def q(wid):
    return urllib.parse.quote(wid, safe="")


def open_tester_session(w) -> str:
    code, d = call(w, "/api/new", {"i": 0})
    assert code == 200, d
    assert d["id"].startswith("t:demo:@")
    assert wait(lambda: any(s["id"] == d["id"] for s in call(w, "/api/sessions")[1]["sessions"]))
    return d["id"]


def test_tester_sees_only_own_space(world):
    w = world
    wid = open_tester_session(w)
    ids = [s["id"] for s in call(w, "/api/sessions")[1]["sessions"]]
    assert ids == [wid]                                       # ни окна владельца, ни чужого пространства
    # новая сессия — в tmux пространства demo, у владельца окон не прибавилось
    assert len(w["own"].windows()) == w["own_n"]
    assert [x["id"] for x in tenants.tmux_of("demo").windows() if x["cmd"] == "claude"] == [spaces.split(wid)[1]]
    # владелец своих окон не теряет и (пока сам не попросит) окон пространств в списке не видит
    own_ids = [s["id"] for s in call(w, "/api/sessions", who=OWNER)[1]["sessions"]]
    assert w["owner_w"] in own_ids and not any(i.startswith("t:") for i in own_ids)


@pytest.mark.parametrize("target", ["owner", "other"])
def test_tester_cannot_touch_foreign_windows(world, target):
    w = world
    open_tester_session(w)
    wid = w["owner_w"] if target == "owner" else w["other_w"]
    for path in ("/api/screen", "/api/history", "/api/last", "/api/hint", "/api/ask", "/api/activity", "/api/tts"):
        code, d = call(w, f"{path}?w={q(wid)}")
        assert code == 404 and d.get("error") == "окна уже нет", (path, code, d)
    for path, body in (("/api/send", {"text": "rm -rf ~"}), ("/api/key", {"key": "Enter"}),
                       ("/api/select", {"target": "1"}), ("/api/rename", {"name": "взлом"}),
                       ("/api/command", {"i": 0})):
        code, d = call(w, path, {"w": wid, **body})
        assert code == 404, (path, code, d)
    # текст до окна не дошёл, имя не сменилось
    tm = w["own"] if target == "owner" else tenants.tmux_of("other")
    raw = spaces.split(wid)[1]
    time.sleep(0.5)
    assert "rm -rf" not in "\n".join(tm.screen(raw, 60))
    assert tm.window(raw)["name"] in ("owner-secret", "other-1")


def test_activity_cache_does_not_leak(world):
    """Строка статуса кэширует список окон на 3 с: владелец заполнил кэш своим окном — тестировщику оно не видно."""
    w = world
    assert call(w, f"/api/activity?w={q(w['owner_w'])}", who=OWNER)[0] == 200
    assert call(w, f"/api/activity?w={q(w['owner_w'])}")[0] == 404


def test_tester_works_in_own_window(world):
    w = world
    wid = open_tester_session(w)
    assert call(w, "/api/send", {"w": wid, "text": "привет"})[0] == 200
    assert wait(lambda: "got: привет" in "\n".join(call(w, f"/api/screen?w={q(wid)}")[1].get("lines", [])))
    assert call(w, "/api/rename", {"w": wid, "name": "моя"})[1]["name"] == "моя"


@pytest.mark.parametrize("path,body", [
    ("/api/mcp", None), ("/api/modules", None), ("/api/people", None), ("/api/providers", None),
    ("/api/setup/status", None), ("/api/commands", None), ("/api/fallback", None), ("/api/team", None),
    ("/api/folder", {"name": "x"}), ("/api/modules/create", {"id": "night-shift", "name": "x"}),
    ("/api/upload", {}), ("/api/active", {"w": "@1"}), ("/api/model", {"w": "@1", "name": "x"}),
    ("/api/mcp/add", {"preset": "github"}), ("/api/keys", {"provider": "openrouter", "key": "x"}),
    ("/api/revive", {"w": "@1"}), ("/api/restart", {"w": "@1"}),
])
def test_tester_blocked_paths(world, path, body):
    code, d = call(world, path, body)
    assert code == 403 and d.get("code") == "space", (path, code, d)


def test_tester_meta_and_view(world):
    w = world
    m = call(w, "/api/meta")[1]
    assert m["projects"] == [] and m["host"] == "Демо для кафе" and m["profiles"] == []
    assert m["space"]["slug"] == "demo" and m["ui"]["persona"] == "point_admin" and m["ui"]["space"]["slug"] == "demo"
    assert m["ui"]["onboarded"] is True
    assert call(w, "/api/persona", {"persona": "developer"})[0] == 400          # вид задаёт владелец
    s = call(w, "/api/sessions")[1]
    assert s["host"] == "Демо для кафе" and s["fallback"] == [] and s["space"]["slug"] == "demo"
    # обычный участник и владелец — как раньше
    assert "space" not in call(w, "/api/meta", who=MEMBER)[1]
    assert call(w, "/api/meta", who=OWNER)[1]["projects"]


def test_disabled_hides_everything(world):
    w = world
    (w["root"] / tenants.MARKER).unlink()                     # настройки нет — функция выключена
    assert call(w, "/api/sessions")[1]["sessions"] == []
    code, d = call(w, "/api/new", {"i": 0})
    assert code == 400 and "не готово" in d["error"]
    assert call(w, "/api/mcp")[0] == 403                       # и по-прежнему ничего чужого
    assert len(w["own"].windows()) == w["own_n"]


def test_people_tenant_field(tmp_path):
    ppl = people.People(tmp_path / "people.json", [1])
    ppl.add(5, "member", "Т", tenant="demo")
    assert ppl.tenant(5) == "demo"
    ppl.add(5, "viewer", "Т")                                  # смена роли не снимает пространство
    assert ppl.tenant(5) == "demo" and ppl.role(5) == "viewer"
    ppl.add(5, "member", "Т", tenant="")                      # снять — явно
    assert ppl.tenant(5) is None
    with pytest.raises(ValueError):
        ppl.add(6, "member", tenant="../etc")
    assert ppl.tenant(1) is None
    ppl.remove(5)
    assert ppl.tenant(5) is None


def test_home_and_pool_of_space_window(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_TENANTS_ROOT", str(tmp_path))
    assert people.home_of({"space": "demo", "by": ""}) == tmp_path / "demo/config/claude"


def test_routed_scope_unit():
    class T:
        def __init__(self, tag):
            self.tag, self.calls = tag, []

        def windows(self):
            return [{"id": "@1", "name": self.tag, "cmd": "claude"}]

        def window(self, wid):
            return next((x for x in self.windows() if x["id"] == wid), None)

        def screen(self, wid, n=25):
            self.calls.append(("screen", wid))
            return [self.tag]

        def run(self, *a, input=None):
            self.calls.append(a)
            return ""

    own, sp = T("owner"), {"demo": T("demo"), "other": T("other")}
    r = spaces.Routed(own, space_of=lambda s: spaces.Space(s, sp[s]), slugs=lambda: ["demo", "other"])
    assert [x["id"] for x in r.windows()] == ["@1"]
    with r.all_spaces():
        assert [x["id"] for x in r.windows()] == ["@1", "t:demo:@1", "t:other:@1"]
    assert r.screen("t:other:@1") == ["other"]                # владелец — в любое пространство
    with r.scope("demo"):
        assert [x["id"] for x in r.windows()] == ["t:demo:@1"]
        assert r.screen("t:demo:@1") == ["demo"]
        assert r.window("@1") is None and r.window("t:other:@1") is None
        for wid in ("@1", "t:other:@1", "t:demo:@1;x", ""):
            with pytest.raises(LookupError):
                r.screen(wid)
        with pytest.raises(LookupError):
            r.run("set-option", "-w", "-t", "@1", "@x", "1")
        with pytest.raises(PermissionError):
            r.new_window("x", "/", "claude")
        r.run("set-option", "-w", "-t", "t:demo:@1", "@x", "1")
    assert sp["demo"].calls[-1] == ("set-option", "-w", "-t", "@1", "@x", "1")
    assert own.calls == [] and ("screen", "@1") not in sp["other"].calls[1:]


class FakeApi:
    def __init__(self):
        self.calls = []

    def __call__(self, method, files=None, **params):
        self.calls.append((method, params))
        return {}

    def redact(self, text):
        return str(text)


def test_bot_offers_tester_button_only_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GAS_PULT_TENANTS_ROOT", str(tmp_path / "t"))
    p = bot.Pult(Config(token="t", owners=[1], session="test"))
    p.api = FakeApi()
    u = {"id": 55, "first_name": "Новый"}
    p.ask_owner(u)
    rows = [b["callback_data"] for m, x in p.api.calls if m == "sendMessage"
            for r in x["reply_markup"]["inline_keyboard"] for b in r]
    assert "pt:55" not in rows                                # пространства выключены — кнопки нет
    (tmp_path / "t/demo").mkdir(parents=True)
    (tmp_path / "t" / tenants.MARKER).write_text("{}")
    (tmp_path / "t/demo" / tenants.META).write_text(json.dumps({"title": "Демо"}))
    p.api.calls.clear()
    p.ask_owner(u)
    rows = [b["callback_data"] for m, x in p.api.calls if m == "sendMessage"
            for r in x["reply_markup"]["inline_keyboard"] for b in r]
    assert "pt:55" in rows
    p.pick_space(1, "55")
    assert any("ps:55:demo" in json.dumps(x.get("reply_markup")) for _, x in p.api.calls)
    p.grant_space(1, "55:demo")
    assert p.people.tenant(55) == "demo" and p.people.role(55) == "member"
    assert any(x.get("chat_id") == 55 and "тестировщик" in x.get("text", "") for _, x in p.api.calls)
    p.grant_space(1, "56:nope")                               # нет такого пространства — не выдаём
    assert p.people.role(56) is None
    # /start тестировщика: инструкция (бот пропускает его сообщение), обычному участнику — нет
    p.people.accept(55)                                       # условия и страна — как у всех, до инструкции
    p.people.set_country(55, chosen="NL")
    upd = {"message": {"message_id": 1, "chat": {"id": 55}, "from": {"id": 55}, "text": "/start"}}
    assert p.admitted(upd)
    p.api.calls.clear()
    p.handle(upd)
    assert any("📱 Панель" in x.get("text", "") for _, x in p.api.calls if _ == "sendMessage")
    p.people.add(57, "member", "Сотрудник")
    assert not p.admitted({"message": {"message_id": 1, "chat": {"id": 57}, "from": {"id": 57}, "text": "/start"}})
