"""Коннектор Т-Бизнес (docs/CONNECTORS.md) — настоящим процессом, без сети.

**Не проверено на песочнице:** fixtures в tests/fixtures/tbank/ собраны по документации T-API
(developer.tbank.ru/docs/api/get-api-v-1-statement и get-api-v-4-bank-accounts, через Context7), данные выдуманные.
Записи в сервис нет вовсе: тесты проверяют, что коннектор ни разу не шлёт запрос на изменение.
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

from gas_pult.connectors import tbank_mcp

SERVER = Path(tbank_mcp.__file__)
FIX = Path(__file__).parent / "fixtures" / "tbank"
KEY = "t." + "testtoken" + "0123456789"                # заведомо не настоящий, склейкой — не для сканера
ROUTES = {"/api/v4/bank-accounts": "accounts", "/api/v1/statement": "statement"}


class Fake(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []
    status = 200

    def log_message(self, *a):
        pass

    def _send(self, code: int, data):
        if isinstance(data, dict):
            data.pop("_source", None)
        elif isinstance(data, list):
            for d in data:
                d.pop("_source", None)
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
                          "body": self.rfile.read(n) if n else None,
                          "headers": {k.lower(): v for k, v in self.headers.items()}})
        if Fake.status != 200:                              # сервис «случайно» повторяет ключ в ответе
            err = json.loads((FIX / "error_401.json").read_text())
            err["errorMessage"] += f" ({KEY})"
            return self._send(Fake.status, err)
        name = ROUTES.get(u.path)
        if self.command != "GET" or not name:
            return self._send(404, {"errorMessage": "Не найдено"})
        self._send(200, json.loads((FIX / f"{name}.json").read_text()))

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _handle


@pytest.fixture
def env(tmp_path):
    Fake.seen, Fake.status = [], 200
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    keyfile = tmp_path / "tbank.token"
    keyfile.write_text(KEY + "\n")
    keyfile.chmod(0o600)
    yield {"GAS_TBANK_BASE": f"http://127.0.0.1:{srv.server_port}", "GAS_TBANK_KEY_FILE": str(keyfile)}
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
    assert out[0]["id"] == 0 and out[0]["result"]["serverInfo"]["name"] == "gas-pult-tbank"
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
    return [s for s in Fake.seen if s["http"] != "GET"]


def test_tools_list(env):
    (r,), _ = rpc([("tools/list", {})], env)
    names = [t["name"] for t in r["result"]["tools"]]
    assert names == ["tbank_list_accounts", "tbank_list_operations"]
    assert all("fn" not in t and t["description"] for t in r["result"]["tools"])


def test_list_accounts(env):
    (r,), _ = rpc([call("tbank_list_accounts")], env)
    rows = body(r)["rows"]
    assert [x["currency"] for x in rows] == ["RUB", "USD"]
    assert rows[0]["balance"] == 152340.5 and rows[0]["main"] and not rows[1]["main"]
    s = Fake.seen[0]
    assert s["http"] == "GET" and s["path"] == "/api/v4/bank-accounts"
    assert s["headers"]["authorization"] == f"Bearer {KEY}"


def test_list_operations(env):
    (r,), _ = rpc([call("tbank_list_operations", {"from": "2026-11-01", "to": "2026-11-26"})], env)
    d = body(r)
    assert d["account"] == "40702810000000000001"           # основной рублёвый счёт взят автоматически
    assert [o["amount"] for o in d["rows"]] == [80000, -25319, -2340.5]
    assert d["rows"][0]["direction"] == "приход" and d["rows"][0]["counterparty"] == "ООО Ромашка Тест"
    assert d["rows"][1]["inn"] == "7700000003" and "Аренда" in d["rows"][1]["purpose"]
    assert d["rows"][2]["status"].startswith("в обработке")
    assert d["period"] == {"balanceBegin": 100000, "balanceEnd": 152340.5, "credit": 80000, "debit": 27659.5}
    assert "more" not in d
    s = Fake.seen[-1]
    assert s["http"] == "GET" and s["path"] == "/api/v1/statement"
    assert s["query"] == {"accountNumber": "40702810000000000001", "from": "2026-11-01T00:00:00Z", "limit": "20",
                          "to": "2026-11-26T00:00:00Z", "withBalances": "true"}


def test_operations_paging_and_filters(env):
    (r,), _ = rpc([call("tbank_list_operations", {"from": "2026-11-01", "account": "40702810000000000001",
                                                   "limit": 3, "direction": "in"})], env)
    d = body(r)
    assert len(d["rows"]) == 1 and "cursor=курсор-следующей-страницы" in d["more"]
    (r2,), _ = rpc([call("tbank_list_operations", {"from": "2026-11-01", "account": "40702810000000000001",
                                                    "cursor": "abc", "status": "Transaction", "inn": "7700000001",
                                                    "limit": 500})], env)
    body(r2)
    q = Fake.seen[-1]["query"]
    assert q["cursor"] == "abc" and "withBalances" not in q and q["limit"] == "100"
    assert q["operationStatus"] == "Transaction" and q["inns"] == "7700000001"


def test_bad_args_no_request(env):
    (r1, r2, r3), _ = rpc([call("tbank_list_operations", {}),
                           call("tbank_list_operations", {"from": "вчера"}),
                           call("tbank_list_operations", {"from": "2026-11-01", "account": "123"})], env)
    assert "from" in err(r1) and "ГГГГ-ММ-ДД" in err(r2) and "20 цифр" in err(r3) and not Fake.seen


@pytest.mark.parametrize("code", [401, 500])
def test_key_not_leaked_on_errors(env, code):
    Fake.status = code
    (r,), stderr = rpc([call("tbank_list_accounts")], env)
    t = err(r)
    assert str(code) in t and KEY not in t and KEY not in stderr


def test_never_writes(env):
    rpc([call("tbank_list_accounts"), call("tbank_list_operations", {"from": "2026-11-01"})], env)
    assert Fake.seen and not writes()


def test_no_payment_tools(env):
    (r,), _ = rpc([("tools/list", {})], env)
    assert not [t for t in r["result"]["tools"] if any(w in t["name"] for w in ("pay", "propose", "apply", "transfer"))]


def test_no_key_file(env, tmp_path):
    e = env | {"GAS_TBANK_KEY_FILE": str(tmp_path / "tbank-нет.token")}
    (r,), _ = rpc([call("tbank_list_accounts")], e)
    assert "tbank-нет.token" in err(r) and not Fake.seen
