"""Вкладки Chrome стола на телефоне — как в Safari (desktabs.py, владелец 22.11).

Поддельный DevTools — локальный HTTP-сервер: ``/json`` (вкладки от активной к давней), ``/json/activate|close|new``
и WebSocket вкладки с ответами на методы ``Page.*`` / ``Browser.*``. Проверяем: список и активная вкладка, верх
страницы в картинке стола (окно минус область страницы), «Назад/Вперёд», миниатюра и её кэш, открыть / закрыть / новая
/ адрес — только пока стол смотрят (сердцебиение мобильного вида), адрес — только http(s); значок «агент» — по
переменам без человека; API — только владельцу и после кода, как сам стол."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_project_chats import call
from test_project_chats import server as server

from gas_pult import desktabs, webapp, wsock

FAV = "data:image/png;base64,iVBORw0KGgo="


class FakeCdp:
    def __init__(self):
        self.tabs = [{"id": "A1", "url": "https://shop.example/", "title": "Магазин", "faviconUrl": FAV},
                     {"id": "B2", "url": "https://news.example/today", "title": "Новости",
                      "faviconUrl": "https://news.example/favicon.ico"}]
        self.http: list[str] = []                       # запросы HTTP (кроме /json)
        self.calls: list[tuple[str, str, dict]] = []    # (вкладка, метод, параметры)
        self.history = {"currentIndex": 1, "entries": [{"id": 10, "url": "https://shop.example/a"},
                                                        {"id": 11, "url": "https://shop.example/"},
                                                        {"id": 12, "url": "https://shop.example/c"}]}
        self.lock = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_PUT(self):
                with fake.lock:
                    fake.http.append("PUT " + self.path)
                    fake.tabs.insert(0, {"id": "N3", "url": self.path.split("?", 1)[1], "title": ""})
                self.json({"id": "N3"})

            def do_GET(self):
                port = self.server.server_address[1]
                if self.path == "/json":
                    with fake.lock:
                        tabs = [dict(t, type="page", webSocketDebuggerUrl=f"ws://127.0.0.1:{port}/devtools/page/{t['id']}")
                                for t in fake.tabs]
                    return self.json([*tabs, {"id": "W", "type": "service_worker"}])
                if self.path.startswith("/json/"):
                    with fake.lock:
                        fake.http.append("GET " + self.path)
                        op, tid = self.path.split("/")[2:4]
                        t = next((x for x in fake.tabs if x["id"] == tid), None)
                        if t and op == "close":
                            fake.tabs.remove(t)
                        if t and op == "activate":
                            fake.tabs.remove(t)
                            fake.tabs.insert(0, t)
                    return self.json("Target activated" if op == "activate" else "Target is closing")
                tid = self.path.rsplit("/", 1)[-1]
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", wsock.accept(self.headers) or "")
                self.end_headers()
                self.wfile.flush()
                try:
                    while True:
                        _, op, data = wsock.read_frame(self.rfile, client=True)
                        if op == wsock.CLOSE:
                            break
                        d = json.loads(data)
                        with fake.lock:
                            fake.calls.append((tid, d["method"], d["params"]))
                        res = fake.answer(d["method"], d["params"])
                        self.wfile.write(wsock.encode(wsock.TEXT, json.dumps({"id": d["id"], "result": res}).encode()))
                        self.wfile.flush()
                except (wsock.Closed, OSError, ValueError):
                    pass
                finally:
                    self.close_connection = True

            def json(self, d):
                body = json.dumps(d).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def answer(self, method, params):
        if method == "Browser.getWindowForTarget":         # окно развёрнуто: 500 × 1009, как на живом столе 22.11
            return {"windowId": 1, "bounds": {"left": 0, "top": 0, "width": 500, "height": 1009,
                                              "windowState": "maximized"}}
        if method == "Page.getLayoutMetrics":              # мобильная эмуляция: макет 1000 × 1776 CSS при zoom 0,5
            return {"cssVisualViewport": {"pageX": 0, "pageY": 40, "clientWidth": 1000, "clientHeight": 1776,
                                          "scale": 1, "zoom": 0.5}, "visualViewport": {"clientHeight": 888}}
        if method == "Page.getNavigationHistory":
            return self.history
        if method == "Page.captureScreenshot":
            return {"data": "/9j/4AAQSkZJRg=="}
        if method == "Page.navigate":
            return {"frameId": "F"}
        return {}

    def methods(self):
        with self.lock:
            return [m for _, m, _ in self.calls]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Watch:
    def __init__(self, on=True):
        self.on = on

    def alive(self):
        return self.on


@pytest.fixture
def cdp():
    f = FakeCdp()
    yield f
    f.srv.shutdown()


def make(cdp, on=True):
    clock = Clock()
    return desktabs.Tabs(cdp=cdp.url, mobile=Watch(on), clock=clock), clock


def test_list_active_top_and_history(cdp):
    t, _ = make(cdp)
    d = t.list()
    assert [x["id"] for x in d["tabs"]] == ["A1", "B2"] and d["active"] == "A1"
    a, b = d["tabs"]
    assert a["active"] and not b["active"] and a["host"] == "shop.example" and a["title"] == "Магазин"
    assert a["icon"] == FAV and b["icon"] == ""              # чужой адрес значка не отдаём — панель рисует букву
    assert d["top"] == 1009 - 888                             # верх страницы: окно минус область страницы (121)
    assert d["back"] is True and d["fwd"] is True
    cdp.history = {"currentIndex": 0, "entries": [{"id": 1, "url": "about:blank"}]}
    d = t.list()
    assert d["back"] is False and d["fwd"] is False


def test_top_bounds_and_fallback():
    class C:
        def __init__(self, win, metrics):
            self.win, self.metrics = win, metrics

        def call(self, m, **_):
            return self.win if m == "Browser.getWindowForTarget" else self.metrics

    win = {"bounds": {"top": 30, "height": 800}}
    assert desktabs.Tabs.page_top(C(win, {"cssVisualViewport": {"clientHeight": 700, "zoom": 1, "scale": 1}})) == 130
    assert desktabs.Tabs.page_top(C(win, {"cssVisualViewport": {}, "visualViewport": {"clientHeight": 680}})) == 150
    assert desktabs.Tabs.page_top(C(win, {"cssVisualViewport": {"clientHeight": 100}})) == 0   # 730 — неправдоподобно
    assert desktabs.Tabs.page_top(C(win, {})) == 0


def test_shot_small_and_cached(cdp):
    t, clock = make(cdp)
    s = t.shot("A1")
    assert s["img"].startswith("data:image/jpeg;base64,/9j/") and s["w"] == 1000
    p = next(p for _, m, p in cdp.calls if m == "Page.captureScreenshot")
    assert p["format"] == "jpeg" and p["quality"] <= 60 and p["clip"]["scale"] == pytest.approx(0.36)
    assert p["clip"]["height"] == 1600 and p["clip"]["y"] == 40   # не выше 1,6 ширины; с места прокрутки
    n = cdp.methods().count("Page.captureScreenshot")
    t.shot("A1")
    assert cdp.methods().count("Page.captureScreenshot") == n    # кэш
    clock.t += desktabs.SHOT_TTL + 1
    t.shot("A1")
    assert cdp.methods().count("Page.captureScreenshot") == n + 1
    with pytest.raises(ValueError):
        t.shot("ZZ")
    with pytest.raises(ValueError):
        t.shot("../json/close/A1")


def test_actions(cdp):
    t, _ = make(cdp)
    assert t.act("open", "B2")["ok"] and cdp.http[-1] == "GET /json/activate/B2"
    assert t.list()["active"] == "B2"
    r = t.act("go", "B2", "example.org/путь")
    assert r["url"] == "https://example.org/путь"
    assert ("B2", "Page.navigate", {"url": "https://example.org/путь"}) in cdp.calls
    assert t.act("back", "B2")["url"] == "https://shop.example/a"
    assert ("B2", "Page.navigateToHistoryEntry", {"entryId": 10}) in cdp.calls
    assert t.act("forward", "B2")["url"] == "https://shop.example/c"
    assert t.act("close", "A1")["ok"] and cdp.http[-1] == "GET /json/close/A1"
    assert [x["id"] for x in t.list()["tabs"]] == ["B2"]
    r = t.act("close", "B2")                                   # последняя: сперва пустая, иначе Chrome закроет окно
    assert r["new"] == "N3" and cdp.http[-2:] == ["PUT /json/new?about:blank", "GET /json/close/B2"]
    assert t.act("new")["id"] == "N3" and cdp.http[-2:] == ["PUT /json/new?about:blank", "GET /json/activate/N3"]
    with pytest.raises(ValueError):
        t.act("open", "ZZ")
    with pytest.raises(ValueError):
        t.act("drop", "A1")


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "file:///etc/passwd", "chrome://settings", "data:text/html,x",
                                 "about:blank", "ftp://x.example/", "view-source:https://x.example/", "a b", "",
                                 "https://", "http:///x", "x" * 5000, "JavaScript:void(0)"])
def test_norm_url_rejects(bad):
    with pytest.raises(ValueError):
        desktabs.norm_url(bad)


def test_norm_url_accepts():
    n = desktabs.norm_url
    assert n("example.com") == "https://example.com"
    assert n("HTTP://Example.com/x?q=1") == "HTTP://Example.com/x?q=1"
    assert n("localhost:8080/app") == "https://localhost:8080/app"
    assert n("//example.com") == "https://example.com"


def test_bad_url_never_reaches_chrome(cdp):
    t, _ = make(cdp)
    with pytest.raises(ValueError):
        t.act("go", "A1", "javascript:alert(1)")
    with pytest.raises(ValueError):
        t.act("new", "", "file:///etc/passwd")
    assert not cdp.calls and not cdp.http


def test_only_while_watching(cdp):
    t, _ = make(cdp, on=False)                                 # стол на телефоне не смотрят — агентам не мешаем
    for op in ("open", "close", "new", "go", "back"):
        with pytest.raises(ValueError, match="только пока"):
            t.act(op, "A1", "example.com")
    assert not cdp.http and not cdp.calls
    assert len(t.list()["tabs"]) == 2                          # смотреть список — можно


def test_agent_badge(cdp):
    t, clock = make(cdp)
    assert not any(x["agent"] for x in t.list()["tabs"])     # первый опрос — без догадок
    clock.t += 30
    cdp.tabs[1]["url"] = "https://news.example/other"          # агент сменил адрес фоновой вкладки
    assert [x["id"] for x in t.list()["tabs"] if x["agent"]] == ["B2"]
    clock.t += 30
    t.act("open", "A1")                                        # человек переключил — не агент
    cdp.tabs[0]["url"] = "https://shop.example/cart"
    assert [x["id"] for x in t.list()["tabs"] if x["agent"]] == ["B2"]
    clock.t += 30
    cdp.tabs[0]["url"] = "https://shop.example/pay"            # человек трогал стол 3 с назад — его
    assert [x["id"] for x in t.list(idle=3)["tabs"] if x["agent"]] == ["B2"]
    clock.t += 30
    cdp.tabs.insert(0, {"id": "C4", "url": "https://docs.example/", "title": "Документы"})   # агент открыл вкладку
    assert [x["id"] for x in t.list()["tabs"] if x["agent"]] == ["C4"]
    clock.t += desktabs.AGENT_TTL + 1                          # давно ничего не делал — значок снят
    assert not any(x["agent"] for x in t.list()["tabs"])


def test_cdp_down():
    t = desktabs.Tabs(cdp="http://127.0.0.1:1", mobile=Watch(True))
    with pytest.raises(ValueError, match="не ответил"):
        t.list()


def test_api_owner_and_confirm_only(server, monkeypatch):
    p, base, *_ = server
    got = []

    class Fake:
        def list(self, idle=None):
            got.append(("list", idle))
            return {"tabs": [], "active": "", "back": False, "fwd": False, "top": 0}

        def shot(self, tid):
            got.append(("shot", tid))
            return {"id": tid, "img": ""}

        def act(self, op, tid="", url=""):
            got.append((op, tid, url))
            return {"ok": True}

    monkeypatch.setattr(desktabs, "TABS", Fake())
    monkeypatch.setattr(webapp, "desktop_up", lambda port=None: True)
    tok = p.auth.issue(1)
    for path in ("/api/desktop/tabs", "/api/desktop/tabs/shot", "/api/desktop/tabs/act"):
        code, e = call(base, path, {}, tok)
        assert code == 403 and e.get("confirm") == "code", path       # свежий вход — сперва код, как у стола
    monkeypatch.setattr(p.auth, "needs_confirm", lambda tok, fresh=None: False)
    for path in ("/api/desktop/tabs", "/api/desktop/tabs/shot", "/api/desktop/tabs/act"):
        assert call(base, path, {"op": "close", "id": "A1"}, p.auth.issue(2))[0] == 403   # участнику — нет
        assert call(base, path, {"op": "close", "id": "A1"}, p.auth.issue(3))[0] == 403   # наблюдателю — нет
    assert not got
    assert call(base, "/api/desktop/tabs", {"idle": 2}, tok)[0] == 200 and got[-1] == ("list", 2)
    assert call(base, "/api/desktop/tabs/shot", {"id": "A1"}, tok)[0] == 200 and got[-1] == ("shot", "A1")
    code, _ = call(base, "/api/desktop/tabs/act", {"op": "go", "id": "A1", "url": "example.com"}, tok)
    assert code == 200 and got[-1] == ("go", "A1", "example.com")
    monkeypatch.setattr(webapp, "desktop_up", lambda port=None: False)
    code, e = call(base, "/api/desktop/tabs", {}, tok)
    assert code == 400 and "не запущен" in e["error"]
