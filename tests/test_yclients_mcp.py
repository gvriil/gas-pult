"""Коннектор YCLIENTS (docs/CONNECTORS.md) — настоящим процессом, без сети.

**Не проверено на песочнице:** fixtures в tests/fixtures/yclients/ собраны по документации YCLIENTS API
(зеркало OpenAPI github.com/alexmaltsevgit/yclients-openapi, через Context7), данные выдуманные. Запись в сервис не
реализована: тесты проверяют, что коннектор ни разу не шлёт запрос на изменение.
"""

import json
import os
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from gas_pult.connectors import yclients_mcp

SERVER = Path(yclients_mcp.__file__)
FIX = Path(__file__).parent / "fixtures" / "yclients"
PARTNER = "test" + "partner" + "0123456789"             # заведомо не настоящие, склейкой — не для сканера
USER = "test" + "usertoken" + "0123456789"
ROUTES = {("GET", "/records/4564"): "records", ("GET", "/record/4564/11"): "record",
          ("POST", "/company/4564/clients/search"): "clients", ("GET", "/company/4564/staff"): "staff",
          ("GET", "/company/4564/services"): "services"}


class Fake(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []
    status = 200

    def log_message(self, *a):
        pass

    def _send(self, code: int, data: dict):
        data.pop("_source", None)
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        u = urllib.parse.urlsplit(self.path)
        Fake.seen.append({"http": self.command, "path": u.path, "query": dict(urllib.parse.parse_qsl(u.query)),
                          "body": json.loads(self.rfile.read(n)) if n else None,
                          "headers": {k.lower(): v for k, v in self.headers.items()}})
        if Fake.status != 200:                              # сервис «случайно» повторяет ключи в ответе
            err = json.loads((FIX / "error_401.json").read_text())
            err["meta"]["message"] += f" ({PARTNER} / {USER})"
            return self._send(Fake.status, err)
        name = ROUTES.get((self.command, u.path))
        if not name:
            return self._send(404, {"success": False, "data": None, "meta": {"message": "Не найдено"}})
        self._send(200, json.loads((FIX / f"{name}.json").read_text()))

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _handle


@pytest.fixture
def env(tmp_path):
    Fake.seen, Fake.status = [], 200
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    keyfile = tmp_path / "yclients.token"
    keyfile.write_text(json.dumps({"partner": PARTNER, "user": USER, "company_id": "4564"}) + "\n")
    keyfile.chmod(0o600)
    yield {"GAS_YCLIENTS_BASE": f"http://127.0.0.1:{srv.server_port}", "GAS_YCLIENTS_KEY_FILE": str(keyfile)}
    srv.shutdown()


def rpc(calls: list[tuple[str, dict]], env: dict) -> tuple[list[dict], str]:
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]
    msgs += [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls, 1)]
    full = {k: v for k, v in os.environ.items() if not k.startswith("GAS_")} | env
    p = subprocess.run([sys.executable, str(SERVER)], input="".join(json.dumps(m) + "\n" for m in msgs),
                       capture_output=True, text=True, timeout=60, env=full)
    out = [json.loads(x) for x in p.stdout.splitlines()]
    assert out[0]["id"] == 0 and out[0]["result"]["serverInfo"]["name"] == "gas-pult-yclients"
    assert len(out) == len(calls) + 1
    for k in (PARTNER, USER):
        assert k not in p.stdout and k not in p.stderr
    return out[1:], p.stderr


def call(name: str, args: dict | None = None) -> tuple[str, dict]:
    return "tools/call", {"name": name, "arguments": args or {}}


def body(resp: dict):
    assert not resp["result"]["isError"], resp["result"]["content"][0]["text"]
    return json.loads(resp["result"]["content"][0]["text"])


def err(resp: dict) -> str:
    assert resp["result"]["isError"]
    return resp["result"]["content"][0]["text"]


def writes() -> list:
    return [s for s in Fake.seen if s["http"] in ("PUT", "PATCH", "DELETE")]


def test_tools_list(env):
    (r,), _ = rpc([("tools/list", {})], env)
    names = [t["name"] for t in r["result"]["tools"]]
    assert names == ["yclients_list_records", "yclients_get_record", "yclients_list_clients", "yclients_list_staff",
                     "yclients_list_services"]
    assert all("fn" not in t and t["description"] for t in r["result"]["tools"])


def test_list_records(env):
    (r,), _ = rpc([call("yclients_list_records", {"limit": 500, "from": "2026-11-26", "to": "2026-11-27",
                                                  "staff_id": "6544"})], env)
    d = body(r)
    assert len(d["rows"]) == 3
    o = d["rows"][0]
    assert o["id"] == 11 and o["client"] == "Иван Тестов" and o["sum"] == 1500 and o["status"] == "ожидается"
    assert o["length_min"] == 60 and o["staff"] == "Анна Т."
    assert d["rows"][1]["status"] == "подтвердил" and d["rows"][2]["deleted"]
    s = Fake.seen[0]
    assert s["http"] == "GET" and s["path"] == "/records/4564"
    assert s["headers"]["authorization"] == f"Bearer {PARTNER}, User {USER}"
    assert s["query"] == {"page": "1", "count": "100", "start_date": "2026-11-26", "end_date": "2026-11-27",
                          "staff_id": "6544"}


def test_bad_args_no_request(env):
    (r1, r2), _ = rpc([call("yclients_list_records", {"from": "вчера"}),
                       call("yclients_get_record", {"id": "x/1"})], env)
    assert "ГГГГ-ММ-ДД" in err(r1) and "id" in err(r2) and not Fake.seen


def test_get_record(env):
    (r,), _ = rpc([call("yclients_get_record", {"id": "11"})], env)
    assert body(r)["id"] == 11 and Fake.seen[0]["path"] == "/record/4564/11"


def test_list_clients(env):
    (r,), _ = rpc([call("yclients_list_clients", {"search": "Иван"})], env)
    d = body(r)
    assert d["rows"][1]["balance"] == -300 and d["rows"][0]["visits"] == 5 and "more" not in d
    s = Fake.seen[0]
    assert s["http"] == "POST" and s["path"] == "/company/4564/clients/search"
    assert s["body"]["filters"][0]["state"]["value"] == "Иван"


def test_staff_services(env):
    (r1, r2), _ = rpc([call("yclients_list_staff"), call("yclients_list_services")], env)
    st, sv = body(r1)["rows"], body(r2)["rows"]
    assert st[0]["active"] and not st[1]["active"] and st[0]["position"] == "Парикмахер"
    assert sv[0]["duration_min"] == 60 and sv[1]["active"] is False


@pytest.mark.parametrize("code", [401, 500])
def test_key_not_leaked_on_errors(env, code):
    Fake.status = code
    (r,), stderr = rpc([call("yclients_list_staff")], env)
    t = err(r)
    assert str(code) in t and PARTNER not in t and USER not in t and PARTNER not in stderr


def test_never_writes(env):
    rpc([call("yclients_list_records"), call("yclients_list_clients"), call("yclients_list_staff"),
         call("yclients_list_services"), call("yclients_get_record", {"id": "11"})], env)
    assert not writes()


def test_no_key_file(env, tmp_path):
    e = env | {"GAS_YCLIENTS_KEY_FILE": str(tmp_path / "yclients-нет.token")}
    (r,), _ = rpc([call("yclients_list_staff")], e)
    assert "yclients-нет.token" in err(r) and not Fake.seen


def test_bad_key_format(env, tmp_path):
    f = tmp_path / "bad.token"
    f.write_text("просто-строка-" + PARTNER)
    (r,), _ = rpc([call("yclients_list_staff")], env | {"GAS_YCLIENTS_KEY_FILE": str(f)})
    assert "JSON" in err(r) and not Fake.seen
