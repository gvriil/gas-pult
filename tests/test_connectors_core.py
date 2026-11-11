"""Ядро коннекторов (docs/CONNECTORS.md): ключ не утекает, запись только после подтверждения человека, MCP по stdio."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gas_pult.connectors import _core

KEY = "test" + "-key-" + "0123456789abcdef"                 # заведомо не настоящий


class Echo401(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):                                        # сервис «случайно» возвращает ключ в тексте ошибки
        body = f"bad token {self.headers.get('Authorization')}".encode()
        self.send_response(401)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def srv():
    s = HTTPServer(("127.0.0.1", 0), Echo401)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def test_http_error_hides_key(srv):
    with pytest.raises(_core.ToolError) as e:
        _core.http("GET", srv + "/x", headers={"Authorization": f"Bearer {KEY}"}, keys=[KEY], service="Тест")
    assert KEY not in str(e.value) and "401" in str(e.value) and "***" in str(e.value)


def test_secret_file(tmp_path, monkeypatch):
    f = tmp_path / "svc.token"
    f.write_text(json.dumps({"client_id": "1234567", "api_key": KEY}))
    monkeypatch.setenv("GAS_SVC_KEY_FILE", str(f))
    raw = _core.read_secret("svc")
    assert set(_core.secret_values(raw)) >= {KEY, "1234567"}
    monkeypatch.setenv("GAS_SVC_KEY_FILE", str(tmp_path / "нет"))
    with pytest.raises(_core.ToolError, match="нет файла ключа"):
        _core.read_secret("svc")


def test_write_needs_flag_and_human(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_CONFIRM_DIR", str(tmp_path))
    d = _core.propose("svc", "create_order", {"sum": 100}, "заказ на 100 ₽")
    with pytest.raises(_core.ToolError, match="запись выключена"):
        _core.take_confirmed("svc", d["id"])
    monkeypatch.setenv("GAS_SVC_WRITE", "1")
    with pytest.raises(_core.ToolError, match="нет подтверждения"):
        _core.take_confirmed("svc", d["id"])
    _core.confirm("svc", d["id"])
    rec = (tmp_path / "svc" / f"{d['id']}.json")
    rec.write_text(rec.read_text().replace('"sum": 100', '"sum": 999'))   # черновик подменили после подтверждения
    with pytest.raises(_core.ToolError, match="нет подтверждения"):
        _core.take_confirmed("svc", d["id"])
    d2 = _core.propose("svc", "create_order", {"sum": 100}, "заказ на 100 ₽")
    assert _core.main({}, "svc", ["confirm", d2["id"]]) == 0
    assert _core.take_confirmed("svc", d2["id"])["params"] == {"sum": 100}
    with pytest.raises(_core.ToolError, match="не найден"):          # одноразово
        _core.take_confirmed("svc", d2["id"])
    with pytest.raises(_core.ToolError, match="неверный id"):
        _core.take_confirmed("svc", "../../etc")


def test_mcp_hides_key_in_any_answer():
    server = {"name": "t", "instructions": "", "keys": lambda: [KEY],
              "tools": [{"name": "t_get", "description": "", "inputSchema": {"type": "object"},
                         "fn": lambda a: {"echo": KEY}}]}
    r = _core.handle(server, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "t_get"}})
    assert KEY not in json.dumps(r) and r["result"]["isError"] is False
    tl = _core.handle(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert tl["result"]["tools"][0]["name"] == "t_get" and "fn" not in tl["result"]["tools"][0]
    assert _core.handle(server, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_throttle():
    t = _core.Throttle(2, 0.2)
    s = time.monotonic()
    for _ in range(3):
        t.wait()
    assert time.monotonic() - s >= 0.15
