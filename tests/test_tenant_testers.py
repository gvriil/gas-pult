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

from gas_pult import bot, people, spaces, tenants, testers, webapp, webauth
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
    # владелец своих окон не теряет и видит окна пространств рядом (п. 6 — группа «Пространства»)
    own_ids = [s["id"] for s in call(w, "/api/sessions", who=OWNER)[1]["sessions"]]
    assert w["owner_w"] in own_ids and wid in own_ids and w["other_w"] in own_ids
    # обычный участник окон пространств не видит
    assert not any(s["id"].startswith("t:") for s in call(w, "/api/sessions", who=MEMBER)[1]["sessions"])


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


# ---------- владелец и сессии пространств (п. 3, 6) ----------
def test_owner_sees_spaces_group_and_works_there(world):
    w = world
    wid = open_tester_session(w)
    ss = {s["id"]: s for s in call(w, "/api/sessions", who=OWNER)[1]["sessions"]}
    assert w["owner_w"] in ss and wid in ss and w["other_w"] in ss
    assert ss[wid]["space"] == "demo" and ss[wid]["space_title"] == "Демо для кафе" and ss[wid]["owner_here"] is None
    assert "space" not in ss[w["owner_w"]]
    # читает и пишет в окно тестировщика; тестировщик видит «Владелец подключился»
    assert call(w, f"/api/screen?w={q(wid)}", who=OWNER)[0] == 200
    assert call(w, "/api/send", {"w": wid, "text": "это владелец"}, who=OWNER)[0] == 200
    assert wait(lambda: "got: это владелец" in "\n".join(call(w, f"/api/screen?w={q(wid)}")[1].get("lines", [])))
    mine = call(w, "/api/sessions")[1]["sessions"]
    assert [s["id"] for s in mine] == [wid] and mine[0]["owner_here"]
    # список тестировщика по-прежнему без окон владельца и чужого пространства
    assert call(w, "/api/active", {"w": wid}, who=OWNER)[0] == 400       # активная в боте — только своё окно


def test_owner_revives_space_window_with_space_command(world, monkeypatch):
    """«Перезапустить» остановленную сессию пространства — командой пространства (tenants.command: свой PATH, профиль
    и ключ), а не командой владельца с его настройками; активной в боте она не становится."""
    w = world
    wid = open_tester_session(w)
    raw = spaces.split(wid)[1]
    tm = tenants.tmux_of("demo")
    tm.run("respawn-pane", "-k", "-t", raw, "bash")                        # Claude вышел — в окне оболочка
    assert wait(lambda: (tm.window(raw) or {}).get("stopped"))
    used = []
    real = tenants.command
    monkeypatch.setattr(tenants, "command", lambda t, base="claude", base_root=None: used.append(t) or real(t))
    active = w["p"].pult.state().get("active")
    assert call(w, "/api/revive", {"w": wid}, who=TESTER)[0] == 403         # тестировщику — нет
    code, d = call(w, "/api/revive", {"w": wid}, who=OWNER)
    assert code == 200 and d["id"] == wid, d
    assert [t.get("title") for t in used] == ["Демо для кафе"]
    assert wait(lambda: any(s["id"] == wid and not s.get("stopped") for s in call(w, "/api/sessions")[1]["sessions"]))
    assert w["p"].pult.state().get("active") == active


def test_owner_connect_and_task(world):
    w = world
    assert call(w, "/api/space/connect", {"w": w["owner_w"]}, who=OWNER)[0] == 400   # не пространство
    assert call(w, "/api/space/connect", {"w": w["other_w"]}, who=OWNER)[1]["ok"] is True
    assert call(w, "/api/space/connect", {"w": w["other_w"]})[0] == 403            # тестировщику — нельзя
    sp = call(w, "/api/spaces", who=OWNER)[1]
    assert sp["enabled"] and {t["slug"] for t in sp["tenants"]} == {"demo", "other"}
    assert call(w, "/api/spaces")[0] == 403
    assert call(w, "/api/space/task", {"space": "demo", "name": "", "task": "x"}, who=OWNER)[0] == 400
    assert call(w, "/api/space/task", {"space": "../x", "name": "a", "task": "x"}, who=OWNER)[0] == 400
    assert call(w, "/api/space/task", {"space": "demo", "name": "Сверка", "task": "x"})[0] == 403
    code, d = call(w, "/api/space/task", {"space": "demo", "name": "Сверка счетов", "task": "разбери inbox"},
                   who=OWNER)
    assert code == 200 and d["id"].startswith("t:demo:@") and d["name"] == "Сверка счетов"
    assert wait(lambda: "got: разбери inbox" in "\n".join(call(w, f"/api/screen?w={q(d['id'])}")[1].get("lines", [])),
                30)
    mine = call(w, "/api/sessions")[1]["sessions"]                     # тестировщик видит её с понятным именем
    assert [(s["id"], s["name"]) for s in mine] == [(d["id"], "Сверка счетов")] and mine[0]["owner_here"]
    assert len(w["own"].windows()) == w["own_n"]


# ---------- «Позвать на помощь», /help, сводка (п. 7, 8) ----------
class PanelApi(FakeApi):
    def __call__(self, method, files=None, **params):
        self.calls.append((method, params))
        if method == "getChatMenuButton":
            return {"type": "web_app", "web_app": {"url": "https://panel.example/"}}
        return {}


def journal(root, slug, path, rows):
    from gas_pult import transcripts
    d = transcripts.project_dir(path, root / slug / "config/claude")
    d.mkdir(parents=True, exist_ok=True)
    (d / "s.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")


def now_iso(shift=0):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + shift))


def test_help_call_from_panel(world):
    w = world
    w["p"].pult.api = PanelApi()
    wid = open_tester_session(w)
    path = call(w, "/api/sessions")[1]["sessions"][0]["path"]
    journal(w["root"], "demo", path, [
        {"type": "user", "timestamp": now_iso(-60), "message": {"content": "сверь счета"}},
        {"type": "assistant", "timestamp": now_iso(-30), "message": {"content": [{"type": "text",
         "text": "Нашёл расхождение.\n\nКакой из двух счетов считать верным?"}], "stop_reason": "end_turn"}}])
    assert call(w, "/api/help/call", {"w": w["owner_w"]})[0] == 404          # чужое окно — «окна нет»
    code, d = call(w, "/api/help/call", {"w": wid})
    assert code == 200 and d["ok"]
    sent = [x for m, x in w["p"].pult.api.calls if m == "sendMessage"]
    assert [x["chat_id"] for x in sent] == [OWNER]
    assert "Тестировщик зовёт на помощь" in sent[0]["text"] and "«Демо для кафе»" in sent[0]["text"]
    assert "Какой из двух счетов считать верным?" in sent[0]["text"]
    url = sent[0]["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"]
    assert url == f"https://panel.example/?session={wid}"
    code, d = call(w, "/api/help/call", {"w": wid})                         # повтор сразу — не спамим
    assert code == 400 and "подождите" in d["error"]
    assert call(w, "/api/help/call", {"w": wid}, who=MEMBER)[0] == 400       # не тестировщик — нельзя


def test_bot_help_and_report(world):
    w = world
    wid = open_tester_session(w)
    path = call(w, "/api/sessions")[1]["sessions"][0]["path"]
    journal(w["root"], "demo", path, [
        {"type": "user", "timestamp": now_iso(-3 * 86400), "message": {"content": "старое сообщение"}},
        {"type": "user", "timestamp": now_iso(-120), "message": {"content": "загрузи выгрузку из СБИС"}},
        {"type": "assistant", "timestamp": now_iso(-100), "message": {"content": [{"type": "text",
         "text": "API Error: 500 Internal server error"}], "stop_reason": "end_turn"}}])
    b = bot.Pult(Config(token="t", owners=[OWNER], session="test"))
    b.api = PanelApi()
    b.people.add(TESTER, "member", "Тестировщик", tenant="demo")
    b.people.accept(TESTER)
    b.people.set_country(TESTER, chosen="NL")
    upd = {"message": {"message_id": 1, "chat": {"id": TESTER}, "from": {"id": TESTER}, "text": "/help"}}
    assert b.admitted(upd)
    b.handle(upd)
    to_owner = [x for m, x in b.api.calls if m == "sendMessage" and x["chat_id"] == OWNER]
    assert to_owner and "зовёт на помощь" in to_owner[0]["text"] and wid in json.dumps(to_owner[0]["reply_markup"])
    assert any("Позвал владельца" in x["text"] for m, x in b.api.calls
               if m == "sendMessage" and x["chat_id"] == TESTER)
    b.handle(upd)                                                       # второй раз сразу — без нового сообщения
    assert len([1 for m, x in b.api.calls if m == "sendMessage" and x["chat_id"] == OWNER]) == 1
    # сводка: что делали (только за сутки), ошибки; обычному участнику /help не открывает ничего
    rep = testers.report(b.people, b.meter)
    assert "«Демо для кафе» — Тестировщик" in rep and "загрузи выгрузку из СБИС" in rep
    assert "старое сообщение" not in rep and "Ошибки (1)" in rep
    b.api.calls.clear()
    b.on_message({"message_id": 2, "chat": {"id": OWNER}, "from": {"id": OWNER}, "text": "/testers"})
    assert any("Тестировщики за 24 ч" in x["text"] for m, x in b.api.calls if m == "sendMessage")
    b.people.remove(TESTER)
    assert testers.report(b.people, b.meter) == ""                       # тестировщиков нет — сводки нет


def test_space_sessions_close_resume_delete_restore(world, monkeypatch, tmp_path):
    """Задача 32, п. 3: у сессии пространства своя папка; «Закрыть» — агент выходит, окно закрыто, папка, файлы и
    разговор остаются (агент работает — сначала «прервать?»; черновик — сохраняем); «Продолжить» — claude --continue
    в той же папке, черновик — обратно; «Удалить» — только закрытую и с именем во втором подтверждении: папка и журнал —
    в корзину пространства на KEEP_DAYS, потом — навсегда; «Восстановить» — обратно."""
    import os as _os

    from gas_pult import space_sessions, transcripts
    w, root = world, world["root"]
    fake = tmp_path / "bin2" / "claude"
    fake.parent.mkdir()
    fake.write_text("#!/usr/bin/env bash\necho \"args: $*\"\nwhile true; do printf '❯ '; IFS= read -r line || exit 0; "
                    "case \"$line\" in /exit) exit 0;; work) echo '✻ Working… (esc to interrupt)';; "
                    "*) echo \"got: $line\";; esac; done\n")
    fake.chmod(0o755)
    monkeypatch.setattr(tenants, "command", lambda t, base="claude", base_root=None: str(fake))
    monkeypatch.setattr(type(w["p"].pult), "QUIT_WAIT", 3.0)
    code, d = call(w, "/api/new", {"i": 0, "name": "Сверка актов"})
    assert code == 200 and d["folder"] == "Сверка актов", d
    wid, home = d["id"], root / "demo" / "home"
    path = home / "projects" / "Сверка актов"
    assert path.is_dir()
    assert wait(lambda: any(s["id"] == wid and s["path"] == str(path) for s in call(w, "/api/sessions")[1]["sessions"]))
    assert call(w, "/api/new", {"i": 0, "name": "Сверка актов"})[1]["folder"] == "Сверка актов 2"   # имя занято
    odd = call(w, "/api/new", {"i": 0, "name": "../../etc/x"})[1]["folder"]           # путь в имени — просто имя
    assert "/" not in odd and (home / "projects" / odd).is_dir() and not (root / "demo" / "etc").exists()
    jdir = transcripts.project_dir(str(path), root / "demo" / "config/claude")
    jdir.mkdir(parents=True)
    (jdir / "s.jsonl").write_text('{"type":"user","message":{"content":"сверь"}}\n')
    raw = spaces.split(wid)[1]
    tm = tenants.tmux_of("demo")
    # агент работает — без подтверждения не закрываем
    assert call(w, "/api/send", {"w": wid, "text": "work"})[0] == 200
    assert wait(lambda: "esc to interrupt" in "\n".join(tm.screen(raw)))
    code, d = call(w, "/api/space/close", {"w": wid})
    assert code == 200 and d["result"] == "busy"
    tm.run("send-keys", "-t", raw, "-l", "недописанный вопрос")                # черновик в поле ввода
    assert wait(lambda: "недописанный вопрос" in "\n".join(tm.screen(raw)))
    code, d = call(w, "/api/space/close", {"w": wid, "force": True})
    assert code == 200 and d["result"] == "closed" and d["draft"] == "недописанный вопрос", d
    assert wait(lambda: tm.window(raw) is None)
    assert path.is_dir() and (jdir / "s.jsonl").exists()                     # файлы и разговор остались
    lst = call(w, "/api/space/sessions")[1]
    mine = {x["folder"]: x for x in lst["closed"]}
    assert mine["Сверка актов"]["history"] and mine["Сверка актов"]["draft"] and lst["keep_days"] == 14
    assert "path" not in mine["Сверка актов"]                               # путей сервера тестировщику не отдаём
    # «Продолжить» — тот же разговор, черновик — обратно
    code, d = call(w, "/api/space/resume", {"folder": "Сверка актов"})
    assert code == 200 and d["continued"] and d["draft"] == "недописанный вопрос", d
    wid2 = d["id"]
    assert wait(lambda: "args: --continue" in "\n".join(tm.screen(spaces.split(wid2)[1])))
    assert call(w, "/api/space/resume", {"folder": "Сверка актов"})[0] == 400        # уже открыта
    assert call(w, "/api/space/delete", {"folder": "Сверка актов", "confirm": "Сверка актов"})[0] == 400   # открыта
    assert call(w, "/api/space/close", {"w": wid2, "force": True})[1]["result"] == "closed"
    # «Удалить» — второе подтверждение именем
    assert call(w, "/api/space/delete", {"folder": "Сверка актов", "confirm": "да"})[0] == 400
    code, d = call(w, "/api/space/delete", {"folder": "Сверка актов", "confirm": "Сверка актов"})
    assert code == 200 and d["keep_days"] == 14, d
    assert not path.exists() and not jdir.exists()
    tr = call(w, "/api/space/sessions")[1]["trash"]
    assert [x["folder"] for x in tr] == ["Сверка актов"] and tr[0]["until"] - tr[0]["deleted"] == 14 * 86400
    entry = root / "demo" / "trash" / "sessions" / tr[0]["id"]
    assert (entry / ".journal" / "s.jsonl").exists()
    # «Восстановить» — папка и разговор на месте
    assert call(w, "/api/space/restore", {"id": tr[0]["id"]})[1]["folder"] == "Сверка актов"
    assert path.is_dir() and (jdir / "s.jsonl").exists() and not entry.exists()
    # через KEEP_DAYS — навсегда
    call(w, "/api/space/delete", {"folder": "Сверка актов", "confirm": "Сверка актов"})
    old = next((root / "demo" / "trash" / "sessions").iterdir())
    t0 = time.time() - (space_sessions.KEEP_DAYS + 2) * 86400
    _os.utime(old, (t0, t0))
    lst = call(w, "/api/space/sessions")
    assert lst[0] == 200 and lst[1]["trash"] == [] and not old.exists(), lst
    # чужое: путь вместо имени, обычный участник; владелец — по имени пространства
    for bad in ("../Сверка актов 2", "/etc", ".journal", ""):
        code, d = call(w, "/api/space/delete", {"folder": bad, "confirm": bad})
        assert code in (400, 404) and str(root) not in d.get("error", ""), (bad, d)
    # ошибка команды в пространстве — понятный текст без самой команды и путей сервера
    code, d = call(w, "/api/space/restore", {"id": "20260101-000000__нет такой"})
    assert code == 400 and d["error"] == "нет такой записи в корзине" and str(root) not in d["error"], d
    assert call(w, "/api/space/sessions", who=MEMBER)[0] == 400
    assert call(w, "/api/space/sessions?space=demo", who=OWNER)[0] == 200
    assert call(w, "/api/space/close", {"w": w["owner_w"]})[0] == 404       # окно владельца — «окна нет»
    # окно в пространстве мимо панели (другая сессия tmux) — его папка не «закрытая»: не продолжить, не удалить
    side = home / "projects" / "Своя работа"
    side.mkdir()
    subprocess.run(["tmux", "-S", w["socks"]["demo"], "new-session", "-d", "-s", "side", "-c", str(side), "sleep 300"],
                   check=True)
    assert "Своя работа" not in {x["folder"] for x in call(w, "/api/space/sessions")[1]["closed"]}
    assert call(w, "/api/space/resume", {"folder": "Своя работа"})[0] == 400
    assert call(w, "/api/space/delete", {"folder": "Своя работа", "confirm": "Своя работа"})[0] == 400
    assert side.is_dir()


def test_space_folder_names():
    from gas_pult import space_sessions
    assert space_sessions.folder_name("Сверка актов") == "Сверка актов"
    for bad in ("../../etc/passwd", "a/b", ".hidden", "~root", "x\ny", "  "):
        n = space_sessions.folder_name(bad)
        assert "/" not in n and not n.startswith((".", "~", "-")) and "\n" not in n and n
    assert len(space_sessions.folder_name("я" * 200)) == space_sessions.NAME_MAX
