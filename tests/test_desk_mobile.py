"""Мобильный вид сайтов в «Браузере» (deskmobile.py, владелец 21.11: «адаптивность как у мобильных браузеров»).

Поддельный DevTools — локальный HTTP-сервер: ``/json``, ``/json/version`` и WebSocket вкладки (кадры клиента — с
маской, ответы — без). Проверяем: включение шлёт три метода эмуляции каждой вкладке, новая вкладка подхватывается,
выключение и молчание панели закрывают подключения (Chrome сам снимает эмуляцию), сбой DevTools не роняет цикл;
``/api/desktop/mobile`` — только владельцу и после кода подтверждения, как сам стол."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_project_chats import call
from test_project_chats import server as server

from gas_pult import deskmobile, desktop, wsock

EMU = ["Emulation.setDeviceMetricsOverride", "Emulation.setUserAgentOverride", "Emulation.setTouchEmulationEnabled"]


class FakeCdp:
    def __init__(self):
        self.tabs = ["A"]
        self.calls: list[tuple[str, str, dict]] = []    # (вкладка, метод, параметры)
        self.open: set[str] = set()                     # вкладки с открытым подключением
        self.lock = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                port = self.server.server_address[1]
                if self.path == "/json/version":
                    return self.json({"Browser": "Chrome/157.0.8103.78"})
                if self.path == "/json":
                    return self.json([{"id": t, "type": "page", "url": "https://example.com/",
                                       "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/{t}"}
                                      for t in fake.tabs] + [{"id": "W", "type": "service_worker"}])
                tid = self.path.rsplit("/", 1)[-1]
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", wsock.accept(self.headers) or "")
                self.end_headers()
                self.wfile.flush()
                with fake.lock:
                    fake.open.add(tid)
                try:
                    while True:
                        _, op, data = wsock.read_frame(self.rfile, client=True)
                        if op == wsock.CLOSE:
                            break
                        d = json.loads(data)
                        with fake.lock:
                            fake.calls.append((tid, d["method"], d["params"]))
                        self.wfile.write(wsock.encode(wsock.TEXT, json.dumps({"method": "Page.event"}).encode()))
                        self.wfile.write(wsock.encode(wsock.TEXT, json.dumps({"id": d["id"], "result": {}}).encode()))
                        self.wfile.flush()
                except (wsock.Closed, OSError, ValueError):
                    pass
                finally:
                    with fake.lock:
                        fake.open.discard(tid)
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

    def methods(self, tid):
        with self.lock:
            return [m for t, m, _ in self.calls if t == tid]


def wait(cond, secs=5.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def cdp():
    f = FakeCdp()
    yield f
    f.srv.shutdown()


def test_on_sends_three_methods_and_off_closes(cdp):
    m = deskmobile.MobileView(cdp=cdp.url, poll=0.05)
    m.set(True, 390, 844, 3)
    assert wait(lambda: cdp.methods("A") == EMU), cdp.calls
    params = {meth: p for t, meth, p in cdp.calls}
    assert params[EMU[0]]["mobile"] is True and params[EMU[0]]["width"] == 0 and params[EMU[0]]["screenWidth"] == 390
    assert "Android" in params[EMU[1]]["userAgent"] and "Chrome/157.0.0.0 Mobile" in params[EMU[1]]["userAgent"]
    assert params[EMU[2]]["enabled"] is True
    assert cdp.open == {"A"} and m.status()["tabs"] == 1
    cdp.tabs.append("B")                                      # агент открыл новую вкладку — подхватили
    assert wait(lambda: cdp.methods("B") == EMU)
    m.set(True, 390, 844, 3)                                  # сердцебиение с теми же параметрами — без повторов
    time.sleep(0.2)
    assert cdp.methods("A") == EMU
    m.set(True, 844, 390, 3)                                  # повернули телефон — переставить, подключение то же
    assert wait(lambda: cdp.methods("A") == EMU * 2)
    cdp.tabs.remove("B")                                      # вкладку закрыли — подключение забыли
    assert wait(lambda: m.status()["tabs"] == 1)
    assert m.set(False)["on"] is False
    assert wait(lambda: not cdp.open and m.status()["tabs"] == 0), cdp.open   # закрыты — Chrome снимет эмуляцию
    m.set(True, 390, 844, 3)                                  # «Переподключить»: выкл и сразу вкл — снова включено
    assert wait(lambda: cdp.open == {"A"} and cdp.methods("A") == EMU * 3)
    m.set(False)
    assert wait(lambda: not cdp.open)


def test_no_heartbeat_turns_off(cdp):
    m = deskmobile.MobileView(cdp=cdp.url, poll=0.05, ttl=0.3)
    m.set(True, 390, 844, 2)
    assert wait(lambda: cdp.open == {"A"})
    assert wait(lambda: not cdp.open and not m.status()["on"], 3), "без сердцебиения не выключилось"


def test_cdp_down_does_not_crash():
    m = deskmobile.MobileView(cdp="http://127.0.0.1:1", poll=0.05)   # порт 1 никто не слушает
    st = m.set(True, 390, 844, 3)
    assert st["on"] is True
    assert wait(lambda: m.status()["error"] != "")
    assert m.thread.is_alive()                                # цикл жив — Chrome поднимется, попробуем снова
    m.set(False)
    assert wait(lambda: not m.status()["on"])


def test_only_local_devtools():
    with pytest.raises(deskmobile.CdpError):
        deskmobile.Conn("ws://example.com:9222/devtools/page/X")


def test_mobile_ua_and_clamp():
    assert "Chrome/157.0.0.0 Mobile Safari" in deskmobile.mobile_ua({"Browser": "Chrome/157.0.8103.78"})
    assert "Chrome/130.0.0.0" in deskmobile.mobile_ua({})
    assert deskmobile.clamp("x", 1, 4, 1.0) == 1.0 and deskmobile.clamp(9, 1, 4, 1.0) == 4


def test_api_owner_and_confirm_only(server, monkeypatch):
    p, base, *_ = server
    got = []

    class Fake:
        def set(self, on, w=0, h=0, dpr=1):
            got.append((on, w, h, dpr))
            return {"on": on, "tabs": 0, "error": ""}

    monkeypatch.setattr(deskmobile, "MOBILE", Fake())
    monkeypatch.setattr(desktop, "desktop_up", lambda port=None: True)
    tok = p.auth.issue(1)
    code, e = call(base, "/api/desktop/mobile", {"on": True}, tok)
    assert code == 403 and e.get("confirm") == "code" and not got        # свежий вход — сперва код, как у стола
    monkeypatch.setattr(p.auth, "needs_confirm", lambda tok, fresh=None: False)
    assert call(base, "/api/desktop/mobile", {"on": True, "w": 390, "h": 844, "dpr": 3}, p.auth.issue(2))[0] == 403
    assert call(base, "/api/desktop/mobile", {"on": True}, p.auth.issue(3))[0] == 403
    assert not got                                                       # участнику и наблюдателю — нет
    code, d = call(base, "/api/desktop/mobile", {"on": True, "w": 390, "h": 844, "dpr": 3}, tok)
    assert code == 200 and d["on"] is True and got[-1] == (True, 390, 844, 3)
    assert call(base, "/api/desktop/mobile", {"on": False}, tok)[1]["on"] is False
    monkeypatch.setattr(desktop, "desktop_up", lambda port=None: False)
    code, e = call(base, "/api/desktop/mobile", {"on": True}, tok)
    assert code == 400 and "не запущен" in e["error"]
    assert call(base, "/api/desktop/mobile", {"on": False}, tok)[0] == 200   # выключить можно всегда
