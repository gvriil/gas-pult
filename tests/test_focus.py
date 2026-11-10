"""Режим «Фокус» (задача 41): ссылка на одну сессию, привязка устройства, всё остальное API — 403, «Завершить» гасит
ссылку, «Отозвать», срок, ссылка не в адресе запроса (после «#»)."""

import contextlib
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import focus, webapp, webauth
from gas_pult.config import Config

W1 = {"id": "@1", "name": "shop", "path": "/srv/shop", "cmd": "claude"}
W2 = {"id": "@2", "name": "other", "path": "/srv/other", "cmd": "claude"}


def test_store_binds_first_device_and_keeps_only_hashes(tmp_path):
    f = focus.Focus(tmp_path / "focus.json")
    link = f.new(W1, by=1)
    raw = (tmp_path / "focus.json").read_text()
    assert link["token"] not in raw and (tmp_path / "focus.json").stat().st_mode & 0o777 == 0o600
    cookie, rec = f.open(link["token"], "", "iPhone · Safari")
    assert rec["w"] == "@1" and cookie.split(".")[1] not in (tmp_path / "focus.json").read_text()
    assert f.open(link["token"], cookie)[0] == cookie                       # то же устройство — снова можно
    with pytest.raises(focus.Gone, match="другом устройстве"):
        f.open(link["token"], "")                                           # другое — нет
    with pytest.raises(focus.Gone):
        f.by_cookie(link["id"] + ".чужой")
    assert f.by_cookie(cookie)["w"] == "@1"
    assert f.listing()[0]["device"] == "iPhone · Safari" and "h" not in f.listing()[0]


def test_store_ends_moves_revokes_and_expires(tmp_path):
    f = focus.Focus(tmp_path / "focus.json")
    a, b = f.new(W1, 1), f.new(W2, 1)
    ca, _ = f.open(a["token"], "")
    cb, _ = f.open(b["token"], "")
    assert f.move("@1", "@7") == 1 and f.by_cookie(ca)["w"] == "@7"          # перезапуск с другой моделью
    assert f.end_window("@7") == 1
    with pytest.raises(focus.Gone, match="Сессия завершена"):
        f.by_cookie(ca)
    assert f.revoke(b["id"]) and not f.listing()
    with pytest.raises(focus.Gone, match="отозвал"):
        f.by_cookie(cb)
    old = f.new(W1, 1, ttl=-1)
    with pytest.raises(focus.Gone, match="Срок"):
        f.open(old["token"], "")
    assert focus.TTL == 7 * 86400


class Wins:
    """Окна tmux для панели: только то, что нужно фокусу."""
    def __init__(self):
        self.w = {"@1": dict(W1), "@2": dict(W2)}

    def window(self, wid):
        return self.w.get(str(wid))

    def windows(self):
        return list(self.w.values())

    @contextlib.contextmanager
    def scope(self, slug):
        yield

    all_spaces = contextlib.nullcontext


@pytest.fixture
def server(monkeypatch):
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.accept(1)
    p.people.set_country(1, chosen="NL")
    wins = Wins()
    monkeypatch.setattr(p, "tmux", wins)
    monkeypatch.setattr(p, "window", lambda wid: wins.window(wid))
    monkeypatch.setattr(p, "sessions",
                        lambda pool=None, who=None: [{"id": w["id"], "name": w["name"]} for w in wins.windows()])
    sent, closed, tg = [], [], []
    monkeypatch.setattr(p, "send", lambda w, text, mid="": sent.append((w["id"], text)) or False)
    monkeypatch.setattr(p, "check", lambda profile, uid: None)

    def close_ex(w):
        closed.append(w["id"])
        wins.w.pop(w["id"], None)
        return {"result": "закрыто", "draft": ""}
    monkeypatch.setattr(p, "close_ex", close_ex)
    monkeypatch.setattr(p.pult, "api", lambda method, **kw: tg.append((method, kw)) or {})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield {"p": p, "base": base, "tok": p.auth.issue(1), "wins": wins, "sent": sent, "closed": closed, "tg": tg}
    srv.shutdown()


def call(base, path, body=None, cookie="", headers=None, raw=False):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": cookie, **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            data = r.read()
            return r.status, (data if raw else json.loads(data)), r.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), ""


FX = {focus.HEADER: "1"}


def owner(s):
    return f"{webauth.COOKIE}={s['tok']}"


def open_link(s, wid="@1"):
    code, d, _ = call(s["base"], "/api/focus/new", {"w": wid, "base": s["base"]}, owner(s))
    assert code == 200, d
    token = d["url"].split("#focus=")[1]
    code, r, setc = call(s["base"], "/api/focus/open", {"token": token}, "", FX)
    assert code == 200 and r["ok"], r
    return d, token, setc.split(";")[0]


def test_link_is_fragment_and_cookie_is_strict(server):
    d, token, cookie = open_link(server)
    assert d["url"] == f"{server['base']}/#focus={token}"        # токен после «#»: не уходит на сервер и в журналы
    assert cookie.startswith(focus.COOKIE + "=")
    _, _, setc = call(server["base"], "/api/focus/open", {"token": token}, cookie, FX)
    for attr in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/"):
        assert attr in setc
    code, r, _ = call(server["base"], "/api/focus/open", {"token": token}, "", FX)   # второе устройство
    assert code == 410 and r["code"] == "focus_gone" and "другом устройстве" in r["error"]


def test_focus_sees_only_its_session(server):
    s = server
    _, _, cookie = open_link(s)
    code, d, _ = call(s["base"], "/api/sessions", None, cookie, FX)
    assert code == 200 and [x["id"] for x in d["sessions"]] == ["@1"]
    code, d, _ = call(s["base"], "/api/meta", None, cookie, FX)
    assert code == 200 and d["focus"]["w"] == "@1" and d["via"] == "focus" and d["projects"] == []
    code, _, _ = call(s["base"], "/api/send", {"w": "@1", "text": "привет"}, cookie, FX)
    assert code == 200 and s["sent"] == [("@1", "привет")]
    for path, body in (("/api/send", {"w": "@2", "text": "x"}), ("/api/key", {"w": "@2", "key": "Enter"}),
                       ("/api/new", {"i": 0}), ("/api/people", None), ("/api/focus/list", None),
                       ("/api/rename", {"w": "@1", "name": "x"}), ("/api/active", {"w": "@1"}),
                       ("/api/keys", {"provider": "x", "key": "y"}), ("/api/mcp/add", {"preset": "http"})):
        code, r, _ = call(s["base"], path, body, cookie, FX)
        assert code == 403 and r["code"] == "focus_scope", (path, code, r)
    code, r, _ = call(s["base"], "/api/history?w=@2", None, cookie, FX)
    assert code == 403
    # без заголовка фокуса cookie фокуса ничего не открывает — тоже 403, не вход
    code, r, _ = call(s["base"], "/api/sessions", None, cookie)
    assert code == 403 and r["code"] == "focus_scope"
    assert s["sent"] == [("@1", "привет")]


RUN_PATHS = (("/api/run", {"w": "@1", "i": 0, "sha": "x"}), ("/api/run/term", {"w": "@1", "i": 0, "sha": "x"}),
             ("/api/commands/run", {"id": "x"}), ("/api/commands/term", {"id": "x"}),
             ("/api/term/type", {"w": "@1", "text": "ls"}), ("/api/tty/type", {"w": "@1", "text": "ls"}))


def test_focus_never_runs_commands_on_server(server, monkeypatch):
    """Решение владельца 10.11: «Выполнить» из фокуса убрано — ни по ссылке на сессию, ни на проект, даже в своём."""
    assert not (webapp.FOCUS_POST | webapp.FOCUS_PROJ_POST) & (webapp.CONFIRM | set(webapp.TERM))
    s = server
    ran = []
    monkeypatch.setattr(s["p"], "run", lambda *a, **k: ran.append(a) or {})
    _, _, cookie = open_link(s)
    proj_server(s, monkeypatch)
    _, pcookie = proj_link(s)
    for c in (cookie, pcookie):
        for path, body in RUN_PATHS:
            code, r, _ = call(s["base"], path, body, c, FX)
            assert code == 403 and r["code"] == "focus_scope", (path, code, r)
    assert ran == []


def test_owner_cookie_does_not_widen_focus(server):
    s = server
    _, _, cookie = open_link(s)
    both = cookie + "; " + owner(s)                    # в том же браузере владелец вошёл в пульт
    code, _, _ = call(s["base"], "/api/people", None, both, FX)
    assert code == 403
    code, d, _ = call(s["base"], "/api/sessions", None, both)       # без заголовка — обычный пульт владельца
    assert code == 200 and len(d["sessions"]) == 2


def test_close_in_focus_ends_link(server):
    s = server
    _, _, cookie = open_link(s)
    code, d, _ = call(s["base"], "/api/close", {"w": "@1"}, cookie, FX)
    assert code == 200 and d["result"] == "закрыто" and s["closed"] == ["@1"]
    code, r, _ = call(s["base"], "/api/sessions", None, cookie, FX)
    assert code == 410 and r["code"] == "focus_gone" and "Сессия завершена" in r["error"]


def test_close_from_panel_or_window_gone_ends_link(server, monkeypatch):
    s = server
    _, _, c1 = open_link(s, "@1")
    _, _, c2 = open_link(s, "@2")
    code, d, _ = call(s["base"], "/api/close", {"w": "@1"}, owner(s))             # владелец завершил в пульте
    assert code == 200 and d["result"] == "закрыто"
    assert call(s["base"], "/api/sessions", None, c1, FX)[0] == 410
    s["wins"].w.pop("@2")                                                          # окно пропало (убили в tmux)
    code, r, _ = call(s["base"], "/api/sessions", None, c2, FX)
    assert code == 503 and r["code"] == "focus_wait"            # сначала — как при перезапуске: ссылка жива
    monkeypatch.setattr(focus, "GRACE", 0)                       # окна нет дольше GRACE — сессия завершена
    code, r, _ = call(s["base"], "/api/sessions", None, c2, FX)
    assert code == 410 and "Сессия завершена" in r["error"]
    assert not s["p"].focus.listing()


def test_restart_keeps_link_on_same_folder(server):
    s = server
    _, _, cookie = open_link(s)
    s["wins"].w["@5"] = {**s["wins"].w.pop("@1"), "id": "@5"}                      # перезапуск: новое окно, та же папка
    code, d, _ = call(s["base"], "/api/sessions", None, cookie, FX)
    assert code == 200 and [x["id"] for x in d["sessions"]] == ["@5"]
    assert call(s["base"], "/api/send", {"w": "@5", "text": "x"}, cookie, FX)[0] == 200


def test_restart_gap_keeps_link(server):
    """Перезапуск закрывает окно раньше, чем открывает новое (вживую — секунды): опрос страницы в этот промежуток
    не гасит ссылку (было: 410 «Сессия завершена» посреди смены модели), а после — ссылка уже на новом окне."""
    s = server
    _, _, cookie = open_link(s)
    w = s["wins"].w.pop("@1")                                                      # старое окно закрыто, нового нет
    code, r, _ = call(s["base"], "/api/sessions", None, cookie, FX)
    assert code == 503 and r["code"] == "focus_wait"
    assert call(s["base"], "/api/history?w=@1", None, cookie, FX)[0] == 503
    assert s["p"].focus.listing()                                                  # ссылка жива
    s["wins"].w["@6"] = {**w, "id": "@6"}                                          # новое окно той же папки
    code, d, _ = call(s["base"], "/api/sessions", None, cookie, FX)
    assert code == 200 and [x["id"] for x in d["sessions"]] == ["@6"]
    assert not s["p"].focus_gap


def test_gone_link_open_is_one_response(server):
    """Погасшая ссылка — ровно один ответ 410 (было: 410, а следом в то же соединение — ещё «200 null»)."""
    import socket
    s = server
    host, port = s["base"].removeprefix("http://").split(":")
    body = json.dumps({"token": "x" * 40}).encode()
    with socket.create_connection((host, int(port))) as c:
        c.sendall(b"POST /api/focus/open HTTP/1.0\r\nContent-Type: application/json\r\nX-Gp-Focus: 1\r\n"
                  b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        raw = b""
        while chunk := c.recv(65536):
            raw += chunk
    assert raw.startswith(b"HTTP/1.0 410") and raw.count(b"HTTP/1.") == 1, raw


def test_owner_list_revoke_qr_and_send_to_telegram(server):
    s = server
    d, token, cookie = open_link(s)
    code, r, _ = call(s["base"], "/api/focus/list", None, owner(s))
    assert code == 200 and r["links"][0]["name"] == "shop" and token not in json.dumps(r)
    code, png, _ = call(s["base"], "/api/focus/qr", {"url": d["url"]}, owner(s), raw=True)
    assert code == 200 and png[:4] == b"\x89PNG"
    code, _, _ = call(s["base"], "/api/focus/send", {"url": d["url"]}, owner(s))
    method, kw = s["tg"][-1]
    assert code == 200 and method == "sendMessage" and kw["chat_id"] == 1 and d["url"] in kw["text"]
    buttons = [b for row in kw["reply_markup"]["inline_keyboard"] for b in row]
    assert {"url": d["url"]} == {"url": buttons[0]["url"]} and buttons[1]["web_app"]["url"] == d["url"]
    code, r, _ = call(s["base"], "/api/focus/revoke", {"id": d["id"]}, owner(s))
    assert code == 200 and r["ok"] and r["links"] == []
    code, r, _ = call(s["base"], "/api/sessions", None, cookie, FX)
    assert code == 410 and "отозвал" in r["error"]
    code, r, _ = call(s["base"], "/api/focus/send", {"url": d["url"]}, owner(s))   # погасшую — не шлём
    assert code == 404


def test_only_owner_issues_links(server):
    s = server
    assert {"/api/focus/new", "/api/focus/send", "/api/focus/qr", "/api/focus/list",
            "/api/focus/revoke"} <= webapp.OWNER_ONLY
    code, _, _ = call(s["base"], "/api/focus/new", {"w": "@1", "base": s["base"]})
    assert code == 401


def test_expired_link(server, monkeypatch):
    s = server
    _, _, cookie = open_link(s)
    real = time.time
    monkeypatch.setattr(focus.time, "time", lambda: real() + focus.TTL + 5)
    code, r, _ = call(s["base"], "/api/sessions", None, cookie, FX)
    assert code == 410 and "Срок" in r["error"]


def test_e2e_focus_in_browser():
    import importlib.util
    import shutil
    from functools import partial
    from http.server import SimpleHTTPRequestHandler
    from pathlib import Path

    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    web = Path(webapp.__file__).resolve().parent / "web"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(web)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    e2e = Path(__file__).resolve().parent / "e2e" / "focus_demo.py"
    spec = importlib.util.spec_from_file_location("focus_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()


def test_e2e_focus_live():
    """Сценарий вживую (tests/e2e/focus_live.py): своя панель, свой tmux, два браузера; без Chrome/tmux — пропуск."""
    import importlib.util
    import shutil
    from pathlib import Path

    pytest.importorskip("playwright.sync_api")
    if not (shutil.which("google-chrome") or shutil.which("chrome")) or not shutil.which("tmux"):
        pytest.skip("нет Chrome или tmux для проверки вживую")
    e2e = Path(__file__).resolve().parent / "e2e" / "focus_live.py"
    spec = importlib.util.spec_from_file_location("focus_live", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert len(mod.run()) == 7


# ---------- фокус на проект: все его сессии, новая сессия в нём, остальное — 403 ----------
def proj_server(s, monkeypatch):
    """Два проекта: «shop» (окна @1 и новые) и «other» (окно @2); проект окна — по папке."""
    p, wins = s["p"], s["wins"]
    data = {"projects": {"p-shop": {"id": "p-shop", "name": "Магазин", "path": "/srv/shop"},
                         "p-other": {"id": "p-other", "name": "Другое", "path": "/srv/other"}}, "sessions": {}}
    monkeypatch.setattr(p, "project_data", lambda wins=None: data)
    of = {"/srv/shop": "p-shop", "/srv/other": "p-other"}
    monkeypatch.setattr(p, "project_of", lambda d, w: of.get(w.get("path"), ""))
    monkeypatch.setattr(p, "sessions", lambda pool=None, who=None: [
        {"id": w["id"], "name": w["name"], "project": of.get(w["path"], "")} for w in wins.windows()])
    made = []

    def project_session(pid, profile="", person=None, uid=None):
        wid = f"@{len(wins.w) + 1}"
        wins.w[wid] = {"id": wid, "name": "shop-2", "path": data["projects"][pid]["path"], "cmd": "claude"}
        made.append((pid, wid))
        return {"id": wid, "project": pid}
    monkeypatch.setattr(p, "project_session", project_session)
    monkeypatch.setattr(p, "project_info", lambda pid, who="owner": {"id": pid, "name": data["projects"][pid]["name"]})
    monkeypatch.setattr(p, "project_chats", lambda pid, q="", before=None, person=None: {"chats": [], "more": False})
    return data, made


def proj_link(s, pid="p-shop"):
    code, d, _ = call(s["base"], "/api/focus/new", {"base": s["base"], "proj": pid}, owner(s))
    assert code == 200 and d["proj"] == pid and d["name"] == "Магазин", d
    code, _, setc = call(s["base"], "/api/focus/open", {"token": d["url"].split("#focus=")[1]}, "", FX)
    assert code == 200
    return d, setc.split(";")[0]


def test_project_link_sees_its_project_only(server, monkeypatch):
    s = server
    data, made = proj_server(s, monkeypatch)
    d, cookie = proj_link(s)
    code, m, _ = call(s["base"], "/api/meta", None, cookie, FX)
    assert code == 200 and m["focus"]["proj"] == "p-shop" and m["focus"]["exp"] == d["exp"] and m["focus"]["w"] == ""
    code, r, _ = call(s["base"], "/api/sessions", None, cookie, FX)
    assert [x["id"] for x in r["sessions"]] == ["@1"]                                 # только окна проекта
    assert call(s["base"], "/api/project?id=p-shop", None, cookie, FX)[0] == 200
    assert call(s["base"], "/api/project/sessions?id=p-shop", None, cookie, FX)[0] == 200   # завершённые чаты
    # новая сессия в проекте — и она сразу доступна
    code, r, _ = call(s["base"], "/api/project/session", {"id": "p-shop"}, cookie, FX)
    assert code == 200 and made == [("p-shop", r["id"])]
    assert call(s["base"], "/api/send", {"w": r["id"], "text": "привет"}, cookie, FX)[0] == 200
    code, ss, _ = call(s["base"], "/api/sessions", None, cookie, FX)
    assert sorted(x["id"] for x in ss["sessions"]) == ["@1", r["id"]]
    # чужой проект и его окно — 403; общий список проектов, люди, новая папка — 403
    for path, body in (("/api/project?id=p-other", None), ("/api/project/sessions?id=p-other", None),
                       ("/api/project/session", {"id": "p-other"}),
                       ("/api/project/resume", {"id": "p-other", "sid": "x"}),
                       ("/api/send", {"w": "@2", "text": "x"}), ("/api/history?w=@2", None), ("/api/projects", None),
                       ("/api/people", None), ("/api/new", {"i": 0}), ("/api/focus/list", None),
                       ("/api/project/chat", {"id": "p-shop", "sid": "x", "hidden": True})):
        code, r2, _ = call(s["base"], path, body, cookie, FX)
        assert code == 403 and r2.get("code") == "focus_scope", (path, code, r2)
    assert made == [("p-shop", r["id"])]                                            # в чужом проекте ничего не создано
    # «Завершить» одно окно проекта — ссылка на проект живёт
    code, c, _ = call(s["base"], "/api/close", {"w": "@1"}, cookie, FX)
    assert code == 200 and c["result"] == "закрыто" and s["closed"] == ["@1"]
    code, ss, _ = call(s["base"], "/api/sessions", None, cookie, FX)
    assert code == 200 and [x["id"] for x in ss["sessions"]] == [r["id"]]
    assert call(s["base"], "/api/close", {"w": "@2"}, cookie, FX)[0] == 403          # окно другого проекта — нет
    # проект удалили из списка — ссылка гаснет
    data["projects"].pop("p-shop")
    code, r3, _ = call(s["base"], "/api/sessions", None, cookie, FX)
    assert code == 410 and "Проект" in r3["error"]


def test_session_link_cannot_open_project(server, monkeypatch):
    """Старая ссылка на одну сессию — как раньше: проект и другие окна проекта закрыты."""
    s = server
    proj_server(s, monkeypatch)
    s["wins"].w["@3"] = {"id": "@3", "name": "shop-3", "path": "/srv/shop", "cmd": "claude"}
    _, _, cookie = open_link(s)
    for path, body in (("/api/project?id=p-shop", None), ("/api/project/session", {"id": "p-shop"}),
                       ("/api/send", {"w": "@3", "text": "x"})):
        code, r, _ = call(s["base"], path, body, cookie, FX)
        assert code == 403 and r["code"] == "focus_scope", (path, code, r)
    code, r, _ = call(s["base"], "/api/sessions", None, cookie, FX)
    assert [x["id"] for x in r["sessions"]] == ["@1"]
    code, m, _ = call(s["base"], "/api/meta", None, cookie, FX)
    assert m["focus"]["proj"] is None and m["focus"]["w"] == "@1"


def test_project_link_owner_only_and_unknown_project(server, monkeypatch):
    s = server
    proj_server(s, monkeypatch)
    assert call(s["base"], "/api/focus/new", {"base": s["base"], "proj": "p-nope"}, owner(s))[0] == 404
    _, cookie = proj_link(s)
    assert call(s["base"], "/api/focus/new", {"base": s["base"], "proj": "p-shop"}, cookie, FX)[0] == 403
    links = call(s["base"], "/api/focus/list", None, owner(s))[1]["links"]
    assert links[0]["proj"] == "p-shop" and links[0]["name"] == "Магазин"


def test_store_project_link_survives_window_end(tmp_path):
    f = focus.Focus(tmp_path / "focus.json")
    link = f.new({"id": "", "path": "/srv/shop", "name": "Магазин"}, 1, proj="p-shop")
    cookie, rec = f.open(link["token"], "")
    assert rec["proj"] == "p-shop" and rec["w"] == ""
    assert f.end_window("") == 0 and f.move("", "@9") == 0
    assert f.by_cookie(cookie)["proj"] == "p-shop"


def test_e2e_focus_project_live():
    """Фокус на проект вживую (tests/e2e/focus_project_live.py); без Chrome/tmux — пропуск."""
    import importlib.util
    import shutil
    import sys
    from pathlib import Path

    pytest.importorskip("playwright.sync_api")
    if not (shutil.which("google-chrome") or shutil.which("chrome")) or not shutil.which("tmux"):
        pytest.skip("нет Chrome или tmux для проверки вживую")
    e2e = Path(__file__).resolve().parent / "e2e" / "focus_project_live.py"
    sys.path.insert(0, str(e2e.parent))
    spec = importlib.util.spec_from_file_location("focus_project_live", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert len(mod.run()) == 6
