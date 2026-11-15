"""Коннектор СДЭК (docs/CONNECTORS.md) — настоящим процессом, без сети.

Fixtures в tests/fixtures/cdek/ записаны с песочницы api.edu.cdek.ru 15.11.2026 публичной тестовой учётной записью
(телефоны и почта ПВЗ заменены). Исключение — ``order.json``: собран по схеме OpenAPI СДЭК, данные выдуманные —
на песочнице заказ не создавали (создание заказа — действие с деньгами, коннектор его не умеет).

Живой прогон на песочнице — только по ``GAS_CDEK_LIVE=1`` (в CI выключен): ``test_live_sandbox``.
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

from gas_pult.connectors import cdek_mcp

SERVER = Path(cdek_mcp.__file__)
FIX = Path(__file__).parent / "fixtures" / "cdek"
ACCOUNT = "test" + "account" + "0123456789abcdef"            # заведомо не настоящие, склейкой — не для сканера
SECURE = "test" + "secure" + "fedcba9876543210"
TOKEN = "test" + "bearer" + "00112233445566778899"
ORDER_NO = "1106207236"


class Fake(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []
    status = 200

    def log_message(self, *a):
        pass

    def _send(self, code: int, data):
        if isinstance(data, dict):
            data.pop("_source", None)                        # служебная пометка fixture, у СДЭК её нет
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _fix(self, name: str):
        return json.loads((FIX / name).read_text())

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        Fake.seen.append({"http": self.command, "path": u.path, "query": q, "body": body,
                          "auth": self.headers.get("Authorization")})
        path = u.path.removeprefix("/v2")
        if path == "/oauth/token" and self.command == "POST":
            if Fake.status == 401:                           # «случайно» повторяет учётные данные в ошибке
                return self._send(401, {"error": "invalid_client", "error_description": f"bad {q}"})
            return self._send(200, self._fix("token.json") | {"access_token": TOKEN})
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(401, {"errors": [{"code": "v2_token_expired", "message": "token"}]})
        if Fake.status != 200:                               # сервис «случайно» повторяет токен и ключ в ответе
            return self._send(Fake.status, {"errors": [{"code": "v2_internal_error",
                                                        "message": f"{TOKEN} {ACCOUNT} {SECURE}"}]})
        if path == "/location/cities":
            return self._send(200, [] if q.get("city") == "Неттакого" else self._fix("cities.json"))
        if path == "/location/suggest/cities":
            return self._send(200, [] if q.get("name") == "Неттакого" else self._fix("suggest.json"))
        if path == "/deliverypoints":
            return self._send(200, self._fix("deliverypoints.json"))
        if path == "/calculator/tarifflist" and self.command == "POST":
            return self._send(200, self._fix("tarifflist.json"))
        if path == "/calculator/tariff" and self.command == "POST":
            return self._send(200, self._fix("tariff.json"))
        if path == "/orders" and self.command == "GET":
            if q.get("cdek_number") == ORDER_NO or q.get("im_number") == "ZAKAZ-42":
                return self._send(200, self._fix("order.json"))
            return self._send(400, self._fix("order_not_found.json"))
        if path.startswith("/orders/") and self.command == "GET":
            return self._send(200, self._fix("order.json"))
        return self._send(404, {"errors": [{"code": "not_found", "message": self.path}]})

    do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = _handle


@pytest.fixture
def env(tmp_path):
    Fake.seen, Fake.status = [], 200
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    keyfile = tmp_path / "cdek.token"
    keyfile.write_text(json.dumps({"account": ACCOUNT, "secure": SECURE, "test": True}))
    keyfile.chmod(0o600)
    yield {"GAS_CDEK_BASE": f"http://127.0.0.1:{srv.server_port}/v2", "GAS_CDEK_KEY_FILE": str(keyfile)}
    srv.shutdown()


def rpc(calls: list[tuple[str, dict]], env: dict) -> list[dict]:
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]
    msgs += [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls, 1)]
    full = {k: v for k, v in os.environ.items() if not k.startswith("GAS_")} | env
    p = subprocess.run([sys.executable, str(SERVER)], input="".join(json.dumps(m) + "\n" for m in msgs),
                       capture_output=True, text=True, timeout=60, env=full)
    out = [json.loads(x) for x in p.stdout.splitlines()]
    assert out[0]["id"] == 0 and out[0]["result"]["serverInfo"]["name"] == "gas-pult-cdek"
    assert len(out) == len(calls) + 1
    for secret in (ACCOUNT, SECURE, TOKEN):
        assert secret not in p.stdout and secret not in p.stderr
    return out[1:]


def call(name: str, args: dict | None = None) -> tuple[str, dict]:
    return "tools/call", {"name": name, "arguments": args or {}}


def body(resp: dict):
    assert not resp["result"]["isError"], resp["result"]["content"][0]["text"]
    return json.loads(resp["result"]["content"][0]["text"])


def err(resp: dict) -> str:
    assert resp["result"]["isError"]
    return resp["result"]["content"][0]["text"]


def api_calls() -> list:
    return [s for s in Fake.seen if s["path"] != "/v2/oauth/token"]


def test_tools_list(env):
    (r,) = rpc([("tools/list", {})], env)
    names = [t["name"] for t in r["result"]["tools"]]
    assert names == ["cdek_list_cities", "cdek_list_points", "cdek_calc", "cdek_get_order"]
    assert all("fn" not in t and t["description"] for t in r["result"]["tools"])
    assert not Fake.seen


def test_token_once_and_auth(env):
    r1, r2 = rpc([call("cdek_list_cities", {"name": "Москва"}), call("cdek_list_points", {"city": 137})], env)
    body(r1), body(r2)
    tok = [s for s in Fake.seen if s["path"] == "/v2/oauth/token"]
    assert len(tok) == 1, "токен берётся один раз на процесс, пока не истёк"
    assert tok[0]["http"] == "POST" and tok[0]["query"] == {"grant_type": "client_credentials",
                                                            "client_id": ACCOUNT, "client_secret": SECURE}
    assert all(s["auth"] == f"Bearer {TOKEN}" for s in api_calls())


def test_list_cities(env):
    (r,) = rpc([call("cdek_list_cities", {"name": "Москва", "limit": 500})], env)
    d = body(r)
    assert d["среда"] == cdek_mcp.TEST_NOTE, "свой тестовый ключ — песочница, но не публичная запись"
    assert d["rows"][0] == {"code": 44, "city": "Москва", "region": "Москва", "sub_region": "Москва",
                            "country_code": "RU"}
    assert d["rows"][1]["region"] == "Псковская область"
    s = api_calls()[0]
    assert s["path"] == "/v2/location/cities" and s["query"] == {"city": "Москва", "country_codes": "RU",
                                                                  "size": "100"}


def test_list_cities_falls_back_to_suggest(env):
    (r,) = rpc([call("cdek_list_cities", {"name": "Неттакого"})], env)
    assert body(r)["rows"] == []
    assert [s["path"] for s in api_calls()] == ["/v2/location/cities", "/v2/location/suggest/cities"]


def test_list_points_by_name(env):
    (r,) = rpc([call("cdek_list_points", {"city": "Санкт-Петербург", "type": "pvz", "weight_kg": 5,
                                          "cod": True, "limit": 2})], env)
    d = body(r)
    assert d["city_code"] == 137 and d["city"] == "Санкт-Петербург, Россия"
    p = d["rows"][0]
    assert p["code"] == "SPB1" and p["type"] == "PVZ" and p["address"].startswith("191040, Россия")
    assert p["work_time"] == "Пн-Вс 08:00-21:00" and p["weight_max_kg"] == 30.0 and p["cod"] is True
    assert "more" in d
    s1, s2 = api_calls()
    assert s1["path"] == "/v2/location/suggest/cities" and s1["query"]["name"] == "Санкт-Петербург"
    assert s2["path"] == "/v2/deliverypoints"
    assert s2["query"] == {"city_code": "137", "type": "PVZ", "size": "2", "page": "0", "weight_max": "5",
                           "allowed_cod": "true"}


def test_list_points_bad_type(env):
    (r,) = rpc([call("cdek_list_points", {"city": 137, "type": "склад"})], env)
    assert "PVZ" in err(r) and not api_calls()


def test_calc_tariff_list(env):
    (r,) = rpc([call("cdek_calc", {"from_city": 44, "to_city": "137", "weight_g": 2000, "length_cm": 30,
                                   "width_cm": 20, "height_cm": 15, "limit": 3})], env)
    d = body(r)
    assert d["from_city_code"] == 44 and d["to_city_code"] == 137 and len(d["rows"]) == 3
    sums = [x["delivery_sum"] for x in d["rows"]]
    assert sums == sorted(sums) and d["rows"][0]["tariff_code"] == 136 and d["rows"][0]["mode"] == "склад-склад"
    assert "из 17" in d["more"]
    (s,) = api_calls()
    assert s["http"] == "POST" and s["path"] == "/v2/calculator/tarifflist"
    assert s["body"] == {"from_location": {"code": 44}, "to_location": {"code": 137},
                         "packages": [{"weight": 2000, "length": 30, "width": 20, "height": 15}]}


def test_calc_one_tariff(env):
    (r,) = rpc([call("cdek_calc", {"from_city": 44, "to_city": 137, "weight_g": 2000, "tariff_code": 136})], env)
    d = body(r)
    assert d["delivery_sum"] == 200.0 and d["total_sum"] == 240.0 and d["days_max"] == 2
    assert d["date_min"] == "2026-11-16" and d["services"] == [{"code": "INSURANCE", "sum": 0.0}]
    (s,) = api_calls()
    assert s["path"] == "/v2/calculator/tariff" and s["body"]["tariff_code"] == 136


def test_calc_bad_weight(env):
    (r,) = rpc([call("cdek_calc", {"from_city": 44, "to_city": 137, "weight_g": "тяжёлая"})], env)
    assert "weight_g" in err(r) and not api_calls()


def test_calc_unknown_city(env):
    (r,) = rpc([call("cdek_calc", {"from_city": "Неттакого", "to_city": 137, "weight_g": 100})], env)
    assert "не найден" in err(r)


def test_get_order(env):
    r1, r2, r3 = rpc([call("cdek_get_order", {"cdek_number": ORDER_NO}),
                      call("cdek_get_order", {"im_number": "ZAKAZ-42"}),
                      call("cdek_get_order", {"uuid": "72753031-0000-4000-8000-000000000001"})], env)
    d = body(r1)
    assert d["cdek_number"] == ORDER_NO and d["number"] == "ZAKAZ-42"
    assert d["status"] == "Принят на склад до востребования" and d["status_code"] == "ACCEPTED_AT_PICK_UP_POINT"
    assert d["status_city"] == "Санкт-Петербург" and d["to_city"] == "Санкт-Петербург"
    assert [h["code"] for h in d["history"]][-1] == "ACCEPTED" and len(d["history"]) == 4
    assert d["link"] == f"https://www.cdek.ru/ru/tracking?order_id={ORDER_NO}"
    assert "recipient" not in json.dumps(d), "персональные данные получателя не отдаём"
    body(r2), body(r3)
    paths = [(s["path"], s["query"]) for s in api_calls()]
    assert paths == [("/v2/orders", {"cdek_number": ORDER_NO}), ("/v2/orders", {"im_number": "ZAKAZ-42"}),
                     ("/v2/orders/72753031-0000-4000-8000-000000000001", {})]


def test_get_order_not_found(env):
    (r,) = rpc([call("cdek_get_order", {"cdek_number": "1234567890"})], env)
    assert "не найдено" in err(r) and "v2_order_not_found" in err(r)


def test_get_order_bad_args(env):
    r1, r2, r3 = rpc([call("cdek_get_order"), call("cdek_get_order", {"uuid": "../orders"}),
                      call("cdek_get_order", {"cdek_number": "12a"})], env)
    assert "cdek_number, im_number или uuid" in err(r1) and "uuid" in err(r2) and "цифры" in err(r3)
    assert not Fake.seen


def test_only_reads_and_calculations(env):
    """Никаких заказов: единственные POST — токен и калькулятор."""
    rpc([call("cdek_list_cities", {"name": "Москва"}), call("cdek_list_points", {"city": 137}),
         call("cdek_calc", {"from_city": 44, "to_city": 137, "weight_g": 500}),
         call("cdek_get_order", {"cdek_number": ORDER_NO})], env)
    writes = [s for s in Fake.seen if s["http"] != "GET"]
    assert {s["path"] for s in writes} <= {"/v2/oauth/token", "/v2/calculator/tarifflist", "/v2/calculator/tariff"}
    assert not any("propose" in t["name"] or "apply" in t["name"] for t in cdek_mcp.SERVER["tools"])


def test_key_never_leaks_on_error(env):
    for code in (500, 403):
        Fake.status = code
        (r,) = rpc([call("cdek_list_cities", {"name": "Москва"})], env)     # rpc сам проверяет stdout/stderr
        t = err(r)
        assert str(code) in t and "***" in t


def test_bad_credentials(env):
    Fake.status = 401
    (r,) = rpc([call("cdek_list_points", {"city": 137})], env)
    assert "ключ не подходит" in err(r)


def test_bad_key_format(env, tmp_path):
    bad = tmp_path / "bad.token"
    bad.write_text("просто-строка-" + SECURE)
    (r,) = rpc([call("cdek_list_cities", {"name": "Москва"})], env | {"GAS_CDEK_KEY_FILE": str(bad)})
    assert '"account"' in err(r) and not Fake.seen


def test_no_key_file_uses_public_sandbox(env):
    (r,) = rpc([call("cdek_list_cities", {"name": "Москва"})],
               env | {"GAS_CDEK_KEY_FILE": "/nonexistent/cdek.token"})
    d = body(r)
    assert d["среда"] == cdek_mcp.SANDBOX_NOTE
    tok = Fake.seen[0]
    assert tok["query"]["client_id"] == cdek_mcp.SANDBOX["account"]


def test_base_by_test_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("GAS_CDEK_BASE", raising=False)
    f = tmp_path / "k"
    monkeypatch.setenv("GAS_CDEK_KEY_FILE", str(f))
    f.write_text(json.dumps({"account": ACCOUNT, "secure": SECURE}))
    assert cdek_mcp._creds()[1:] == (cdek_mcp.PROD, "")
    f.write_text(json.dumps({"account": ACCOUNT, "secure": SECURE, "test": True}))
    assert cdek_mcp._creds()[1:] == (cdek_mcp.TEST, cdek_mcp.TEST_NOTE)
    monkeypatch.setenv("GAS_CDEK_KEY_FILE", str(tmp_path / "нет"))
    assert cdek_mcp._creds() == (cdek_mcp.SANDBOX, cdek_mcp.TEST, cdek_mcp.SANDBOX_NOTE)


@pytest.mark.skipif(os.environ.get("GAS_CDEK_LIVE") != "1", reason="живая песочница — только по GAS_CDEK_LIVE=1")
def test_live_sandbox(tmp_path):
    """Один живой прогон на api.edu.cdek.ru публичной тестовой учётной записью."""
    env = {"GAS_CDEK_KEY_FILE": str(tmp_path / "нет-ключа")}
    r1, r2, r3, r4 = rpc([call("cdek_list_cities", {"name": "Казань", "limit": 3}),
                          call("cdek_list_points", {"city": 137, "type": "PVZ", "limit": 2}),
                          call("cdek_calc", {"from_city": "Москва", "to_city": 137, "weight_g": 2000,
                                             "tariff_code": 136}),
                          call("cdek_get_order", {"cdek_number": "1234567890"})], env)
    assert any(c["code"] == 424 for c in body(r1)["rows"])
    assert body(r2)["rows"] and body(r3)["total_sum"] > 0
    assert "v2_order_not_found" in err(r4)
