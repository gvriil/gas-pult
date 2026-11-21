"""Коннектор МойСклад (docs/CONNECTORS.md) — настоящим процессом, без сети.

**Не проверено на песочнице:** fixtures в tests/fixtures/moysklad/ собраны по примерам из официальной документации
JSON API 1.2 (github.com/moysklad/api-remap-1.2-doc @012cd53), данные выдуманные. После появления демо-токена ночной
конвейер перезапишет их обезличенными ответами демо-аккаунта.

Фейковый МойСклад, как настоящий, отвечает только в gzip и только при ``Accept-Encoding: gzip`` (иначе 415).
"""

import gzip
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, urlsplit

import pytest

from gas_pult.connectors import moysklad_mcp

SERVER = Path(moysklad_mcp.__file__)
FIX = Path(__file__).parent / "fixtures" / "moysklad"
KEY = "test" + "-key-" + "0123456789abcdef"                 # заведомо не настоящий, склейкой — не для сканера
O1 = "34efe2ee-015e-11e6-9464-e4de0000006b"
ROUTES = {"/api/remap/1.2/report/stock/all": "stock_all.json",
          "/api/remap/1.2/entity/customerorder": "customerorder_list.json",
          f"/api/remap/1.2/entity/customerorder/{O1}": "customerorder_one.json",
          "/api/remap/1.2/entity/customerorder/metadata": "customerorder_metadata.json",
          "/api/remap/1.2/report/counterparty": "counterparty_report.json"}


class Fake(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []
    status = 200

    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes):
        data = json.loads(body)
        if isinstance(data, dict):
            data.pop("_source", None)                       # служебная пометка fixture, у МойСклад её нет
        z = gzip.compress(json.dumps(data, ensure_ascii=False).encode())
        self.send_response(code)
        self.send_header("Content-Type", "application/json;charset=utf-8")
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(z)))
        self.end_headers()
        self.wfile.write(z)

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        u = urlsplit(self.path)
        Fake.seen.append({"method": self.command, "path": u.path, "query": parse_qs(u.query),
                          "headers": {k.lower(): v for k, v in self.headers.items()},
                          "body": json.loads(self.rfile.read(n)) if n else None})
        if self.headers.get("Accept-Encoding") != "gzip":
            self.send_response(415)
            self.end_headers()
            return
        if Fake.status != 200:                              # сервис «случайно» повторяет ключ в ответе
            err = json.loads((FIX / "error_401.json").read_text())
            err["errors"][0]["error"] += f" ({self.headers.get('Authorization')})"
            return self._send(Fake.status, json.dumps(err, ensure_ascii=False).encode())
        if self.command == "PUT":
            return self._send(200, (FIX / "customerorder_one.json").read_bytes())
        f = ROUTES.get(u.path)
        if not f:
            return self._send(404, b'{"errors":[{"error":"not found","code":1021}]}')
        self._send(200, (FIX / f).read_bytes())

    do_GET = do_PUT = do_POST = do_PATCH = do_DELETE = _handle


@pytest.fixture
def env(tmp_path):
    Fake.seen, Fake.status = [], 200
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    keyfile = tmp_path / "moysklad.token"
    keyfile.write_text(KEY + "\n")
    keyfile.chmod(0o600)
    yield {"GAS_MOYSKLAD_BASE": f"http://127.0.0.1:{srv.server_port}/api/remap/1.2",
           "GAS_MOYSKLAD_KEY_FILE": str(keyfile), "GAS_CONFIRM_DIR": str(tmp_path / "confirm")}
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
    assert out[0]["id"] == 0 and out[0]["result"]["serverInfo"]["name"] == "gas-pult-moysklad"
    assert len(out) == len(calls) + 1
    assert KEY not in p.stdout and KEY not in p.stderr
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
    return [s for s in Fake.seen if s["method"] in ("POST", "PUT", "PATCH", "DELETE")]


def test_tools_list(env):
    (r,), _ = rpc([("tools/list", {})], env)
    names = [t["name"] for t in r["result"]["tools"]]
    assert names == ["moysklad_list_stock", "moysklad_list_orders", "moysklad_get_order", "moysklad_list_balances",
                     "moysklad_list_order_states", "moysklad_propose_order_state", "moysklad_apply"]
    assert all("fn" not in t and t["description"] for t in r["result"]["tools"])


def test_list_stock(env):
    (r,), _ = rpc([call("moysklad_list_stock", {"limit": 500, "search": "том;ат", "stock_mode": "underMinimum"})],
                  env)
    d = body(r)
    assert d["total"] == 3 and d["rows"][0]["name"] == "Томаты черри"
    assert d["rows"][0]["sale_price_rub"] == 320.0 and d["rows"][0]["available"] == 10.0
    assert d["rows"][0]["id"] == "c02e3a5c-007e-11e6-9464-e4de00000006" and d["rows"][0]["uom"] == "кг"
    s = Fake.seen[0]
    assert s["method"] == "GET" and s["path"] == "/api/remap/1.2/report/stock/all"
    assert s["query"]["limit"] == ["100"] and s["query"]["filter"] == ["stockMode=underMinimum;search=том ат"]
    assert s["headers"]["authorization"] == f"Bearer {KEY}"
    assert s["headers"]["accept"] == "application/json;charset=utf-8"


def test_list_stock_bad_mode(env):
    (r,), _ = rpc([call("moysklad_list_stock", {"stock_mode": "всё"})], env)
    assert "stock_mode" in err(r) and not Fake.seen


def test_list_orders(env):
    (r,), _ = rpc([call("moysklad_list_orders", {"since": "2026-11-01", "search": "Ромашка"})], env)
    d = body(r)
    o = d["rows"][0]
    assert o["number"] == "00001" and o["customer"] == "ООО «Ромашка-Бистро»" and o["status"] == "Новый"
    assert o["sum_rub"] == 12500.0 and o["date"] == "2026-11-12T12:57:00"
    assert o["link"] == f"https://online.moysklad.ru/app/#customerorder/edit?id={O1}"
    q = Fake.seen[0]["query"]
    assert Fake.seen[0]["path"] == "/api/remap/1.2/entity/customerorder"
    assert q["expand"] == ["agent,state"] and q["order"] == ["moment,desc"] and q["limit"] == ["20"]
    assert q["filter"] == ["moment>=2026-11-01 00:00:00"] and q["search"] == ["Ромашка"]


def test_list_orders_bad_date(env):
    (r,), _ = rpc([call("moysklad_list_orders", {"since": "вчера"})], env)
    assert "ГГГГ-ММ-ДД" in err(r)


def test_get_order(env):
    (r,), _ = rpc([call("moysklad_get_order", {"id": O1.upper()})], env)
    d = body(r)
    assert d["id"] == O1 and len(d["positions"]) == 2
    assert d["positions"][0] == {"name": "Томаты черри", "code": "one1", "qty": 2.5, "price_rub": 3200.0,
                                 "discount_pct": 0, "sum_rub": 8000.0}
    assert Fake.seen[0]["path"] == f"/api/remap/1.2/entity/customerorder/{O1}"
    assert Fake.seen[0]["query"]["expand"] == ["agent,state,positions.assortment"]


def test_get_order_bad_id(env):
    (r,), _ = rpc([call("moysklad_get_order", {"id": "../../context/employee"})], env)
    assert "UUID" in err(r) and not Fake.seen


def test_list_balances(env):
    (r,), _ = rpc([call("moysklad_list_balances", {"search": "Ромашка"})], env)
    d = body(r)
    assert d["rows"][0]["name"] == "ООО «Ромашка-Бистро»" and d["rows"][0]["balance_rub"] == -12500.0
    assert [x["balance_rub"] for x in d["rows"]] == sorted(x["balance_rub"] for x in d["rows"])
    assert "знак" in d["note"].lower()
    assert Fake.seen[0]["path"] == "/api/remap/1.2/report/counterparty"
    assert Fake.seen[0]["query"]["filter"] == ["balance!=0;counterparty.name~Ромашка"]


def test_list_order_states(env):
    (r,), _ = rpc([call("moysklad_list_order_states")], env)
    d = body(r)
    assert [s["name"] for s in d] == ["Новый", "Подтвержден", "Отгружен", "Отменен"]
    assert d[2]["kind"] == "финальный: успех"


def test_key_never_leaks_on_error(env):
    for code in (401, 500):
        Fake.status = code
        (r,), _ = rpc([call("moysklad_list_orders")], env)      # rpc сам проверяет stdout/stderr
        t = err(r)
        assert str(code) in t and "***" in t and KEY not in t


def test_401_hint(env):
    Fake.status = 401
    (r,), _ = rpc([call("moysklad_list_stock")], env)
    assert "ключ не подходит" in err(r) and "Ошибка аутентификации" in err(r)


def test_no_key_file(env):
    (r,), _ = rpc([call("moysklad_list_orders")], env | {"GAS_MOYSKLAD_KEY_FILE": "/nonexistent/moysklad.token"})
    assert "нет файла ключа" in err(r) and "docs/connectors/moysklad.md" in err(r)
    assert not Fake.seen


def test_write_only_after_human(env):
    (p,), _ = rpc([call("moysklad_propose_order_state", {"id": O1, "status": "подтвержден"})], env)
    d = body(p)
    assert d["params"]["state_name"] == "Подтвержден" and "«Новый» → «Подтвержден»" in d["summary"]
    assert not writes(), "propose не должен ничего писать в МойСклад"
    # без флага записи
    (a,), _ = rpc([call("moysklad_apply", {"id": d["id"]})], env)
    assert "запись выключена" in err(a)
    # с флагом, но без подтверждения человека
    (a,), _ = rpc([call("moysklad_apply", {"id": d["id"]})], env | {"GAS_MOYSKLAD_WRITE": "1"})
    assert "нет подтверждения" in err(a) and not writes()
    # человек подтвердил (CLI пульта) — ровно один PUT
    full = {k: v for k, v in os.environ.items() if not k.startswith("GAS_")} | env
    c = subprocess.run([sys.executable, str(SERVER), "confirm", d["id"]], capture_output=True, text=True, env=full)
    assert c.returncode == 0, c.stderr
    (a,), _ = rpc([call("moysklad_apply", {"id": d["id"]})], env | {"GAS_MOYSKLAD_WRITE": "1"})
    assert "Подтвержден" in body(a)["done"]
    w = writes()
    assert len(w) == 1 and w[0]["method"] == "PUT" and w[0]["path"] == f"/api/remap/1.2/entity/customerorder/{O1}"
    assert w[0]["body"]["state"]["meta"]["href"].endswith("/states/fb56c504-2e58-11e6-8a84-bae50000006a")
    # повторно — нельзя
    (a,), _ = rpc([call("moysklad_apply", {"id": d["id"]})], env | {"GAS_MOYSKLAD_WRITE": "1"})
    assert "не найден" in err(a) and len(writes()) == 1


def test_propose_unknown_or_same_state(env):
    (r1, r2), _ = rpc([call("moysklad_propose_order_state", {"id": O1, "status": "Улетел"}),
                       call("moysklad_propose_order_state", {"id": O1, "status": "Новый"})], env)
    assert "нет статуса «Улетел»" in err(r1) and "Подтвержден" in err(r1)
    assert "менять нечего" in body(r2)["status"]
    assert not writes()


def test_throttle_spends_vendor_units(monkeypatch):
    spent = []
    monkeypatch.setattr(moysklad_mcp.THROTTLE, "wait", lambda: spent.append(1))
    monkeypatch.setattr(moysklad_mcp._core, "read_secret", lambda svc: KEY)
    monkeypatch.setattr(moysklad_mcp._core, "http", lambda *a, throttle, **kw: throttle.wait() or {"rows": []})
    moysklad_mcp.list_stock({})
    assert len(spent) == moysklad_mcp.COST_STOCK
    spent.clear()
    moysklad_mcp.list_orders({})
    assert len(spent) == moysklad_mcp.COST
