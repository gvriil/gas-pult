"""Коннектор Ozon Seller (docs/CONNECTORS.md) — настоящим процессом, без сети.

**Не проверено на песочнице** (у Ozon Seller API её нет, ключа ещё нет). Fixtures в tests/fixtures/ozon/ собраны по
примерам ответов из документации Ozon (docs.ozon.ru/api/seller — через индекс Context7 и зеркало
github.com/etozhearut/ozon-seller-api, 19.11.2026), товары и тексты выдуманные. Когда появится ключ «только чтение» —
заменить ответами настоящего кабинета (обезличить).
"""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import panel_stub  # «Да» человека без настоящей панели
import pytest

from gas_pult.connectors import ozon_mcp as oz

SERVER = Path(oz.__file__)
FIX = Path(__file__).parent / "fixtures" / "ozon"
CID = "9" + "87654"                                         # заведомо не настоящие, склейкой — не для сканера
KEY = "test" + "ozonkey" + "-0123-4567-89ab-cdef"
WRITES = {"PUT", "PATCH", "DELETE"}                          # у Ozon всё чтение — POST, запись считаем по пути
WRITE_PATHS = {"/v1/review/comment/create"}


class Fake(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []
    status = 200

    def log_message(self, *a):
        pass

    def _send(self, code: int, data=None):
        raw = b"" if data is None else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        Fake.seen.append({"http": self.command, "path": self.path, "body": body,
                          "cid": self.headers.get("Client-Id"), "key": self.headers.get("Api-Key"),
                          "auth": self.headers.get("Authorization")})
        if self.headers.get("Api-Key") != KEY or self.headers.get("Client-Id") != CID:
            return self._send(401, {"code": 7, "message": f"Invalid Api-Key {self.headers.get('Api-Key')}",
                                    "details": []})
        if Fake.status != 200:                               # сервис «случайно» повторяет ключ в ответе
            return self._send(Fake.status, {"code": 13, "message": f"internal {CID} {KEY}", "details": []})
        routes = {"/v4/product/info/stocks": "stocks.json", "/v5/product/info/prices": "prices.json",
                  "/v4/posting/fbs/list": "postings_fbs.json", "/v3/posting/fbo/list": "postings_fbo.json",
                  "/v2/review/list": "reviews.json"}
        if self.command == "POST" and self.path in routes:
            d = json.loads((FIX / routes[self.path]).read_text())
            d.pop("_source", None)                           # служебная пометка fixture, у Ozon её нет
            return self._send(200, d)
        if self.command == "POST" and self.path in WRITE_PATHS:
            return self._send(200, {"comment_id": "c0ffee00-0000-0000-0000-000000000001"})
        return self._send(404, {"code": 5, "message": "method is not allowed", "details": []})

    do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = _handle


@pytest.fixture
def env(tmp_path):
    Fake.seen, Fake.status = [], 200
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    keyfile = tmp_path / "ozon.token"
    keyfile.write_text(json.dumps({"client_id": CID, "api_key": KEY}) + "\n")
    keyfile.chmod(0o600)
    yield {"GAS_OZON_BASE": f"http://127.0.0.1:{srv.server_port}", "GAS_OZON_KEY_FILE": str(keyfile),
           **panel_stub.env(tmp_path)}
    srv.shutdown()


def full_env(env: dict) -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("GAS_")} | env


def rpc(calls: list[tuple[str, dict]], env: dict) -> list[dict]:
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]
    msgs += [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls, 1)]
    p = subprocess.run([sys.executable, str(SERVER)], input="".join(json.dumps(m) + "\n" for m in msgs),
                       capture_output=True, text=True, timeout=60, env=full_env(env))
    out = [json.loads(x) for x in p.stdout.splitlines()]
    assert out[0]["id"] == 0 and out[0]["result"]["serverInfo"]["name"] == "gas-pult-ozon"
    assert len(out) == len(calls) + 1
    for s in (KEY, CID):
        assert s not in p.stdout and s not in p.stderr
    return out[1:]


def call(name: str, args: dict | None = None) -> tuple[str, dict]:
    return "tools/call", {"name": name, "arguments": args or {}}


def body(resp: dict):
    assert not resp["result"]["isError"], resp["result"]["content"][0]["text"]
    return json.loads(resp["result"]["content"][0]["text"])


def err(resp: dict) -> str:
    assert resp["result"]["isError"]
    return resp["result"]["content"][0]["text"]


def writes() -> list:
    return [s for s in Fake.seen if s["http"] in WRITES or s["path"] in WRITE_PATHS]


def test_tools_list(env):
    (r,) = rpc([("tools/list", {})], env)
    names = [t["name"] for t in r["result"]["tools"]]
    assert names == ["ozon_list_stocks", "ozon_list_prices", "ozon_list_orders", "ozon_list_reviews",
                     "ozon_propose_review_comment", "ozon_apply"]
    assert all("fn" not in t and t["description"] for t in r["result"]["tools"])
    assert not Fake.seen


def test_list_stocks(env):
    (r,) = rpc([call("ozon_list_stocks", {"limit": 2, "offer_id": "TERMO-500"})], env)
    d = body(r)
    a, b = d["rows"]
    assert a["offer_id"] == "TERMO-500" and a["sku"] == 1000123456
    assert a["stocks"] == {"fbs": {"present": 150, "reserved": 25, "available": 125},
                           "fbo": {"present": 75, "reserved": 10, "available": 65}}
    assert a["link"] == "https://www.ozon.ru/product/1000123456/"
    assert b["stocks"] == {"fbs": {"present": 45, "reserved": 5, "available": 40}}
    assert d["total_products"] == 2 and "cursor=next-cursor-12345" in d["more"]
    (s,) = Fake.seen
    assert (s["http"], s["path"]) == ("POST", "/v4/product/info/stocks")
    assert s["cid"] == CID and s["key"] == KEY and s["auth"] is None, "Ozon: заголовки Client-Id и Api-Key"
    assert s["body"] == {"filter": {"visibility": "ALL", "offer_id": ["TERMO-500"]}, "limit": 2, "cursor": ""}


def test_list_prices(env):
    (r,) = rpc([call("ozon_list_prices", {"cursor": "abc"})], env)
    d = body(r)
    (p,) = d["rows"]
    assert p == {"product_id": 1000123456, "offer_id": "TERMO-500", "currency": "RUB", "price": 2999.99,
                 "old_price": 3499.99, "min_price": 2799.99, "net_price": 2000, "price_index": "GREEN",
                 "commission_fbo_pct": 15, "commission_fbs_pct": 12, "actions": ["Скидка 15% на посуду"]}
    assert "more" not in d
    assert Fake.seen[0]["path"] == "/v5/product/info/prices"
    assert Fake.seen[0]["body"] == {"filter": {"visibility": "ALL"}, "limit": 20, "cursor": "abc"}


def test_list_orders_fbs(env):
    (r,) = rpc([call("ozon_list_orders", {"date_from": "2026-11-18", "date_to": "2026-11-18", "limit": 2})], env)
    d = body(r)
    assert d["scheme"] == "fbs" and d["count"] == 2
    assert d["since_utc"] == "2026-11-17T21:00:00Z" and d["to_utc"] == "2026-11-18T21:00:00Z"  # сутки по Москве
    a, b = d["rows"]
    assert a["posting_number"] == "42776709-0200-5" and a["sum"] == 2922.0
    assert a["products"][0] == {"offer_id": "TERMO-500", "name": "Термокружка 500 мл", "sku": 1000123456, "qty": 2,
                                "price": 1461.0, "currency": "RUB"}
    assert b["status"] == "cancelled" and d["sum_not_cancelled"] == 2922.0, "отменённые не в сумме"
    assert "cursor=fbs-cursor-2" in d["more"]
    text = json.dumps(d, ensure_ascii=False)
    assert "Покупател" not in text and "7700000000" not in text and "+7000" not in text, "данных покупателя нет"
    (s,) = Fake.seen
    assert s["path"] == "/v4/posting/fbs/list"
    assert s["body"] == {"filter": {"since": "2026-11-17T21:00:00Z", "to": "2026-11-18T21:00:00Z"},
                         "limit": 2, "cursor": "", "sort_dir": "DESC"}
    assert "with" not in s["body"], "доп. поля (адрес, юр. данные) не запрашиваем"


def test_list_orders_fbo_status(env):
    (r,) = rpc([call("ozon_list_orders", {"scheme": "fbo", "status": "delivered", "date_from": "2026-11-17"})], env)
    d = body(r)
    assert d["rows"][0]["posting_number"] == "9121072335-0187-1" and d["sum_not_cancelled"] == 2990.0
    assert "more" not in d
    s = Fake.seen[0]
    assert s["path"] == "/v3/posting/fbo/list" and s["body"]["filter"]["statuses"] == ["delivered"]


@pytest.mark.parametrize(("args", "msg"), [({"date_from": "вчера"}, "ГГГГ-ММ-ДД"),
                                           ({"scheme": "rfbs"}, "scheme"),
                                           ({"status": "lost"}, "status"),
                                           ({"date_from": "2024-01-01", "date_to": "2026-01-01"}, "года"),
                                           ({"date_from": "2026-11-18", "date_to": "2026-11-10"}, "раньше")])
def test_orders_bad_args_no_request(env, args, msg):
    (r,) = rpc([call("ozon_list_orders", args)], env)
    assert msg in err(r) and not Fake.seen


def test_list_reviews(env):
    (r,) = rpc([call("ozon_list_reviews", {"limit": 1, "status": "new", "sku": 1000123456})], env)
    d = body(r)
    (v,) = d["rows"]
    assert v["id"] == "017c0d1c-66d3-b838-3d29-cf9b95a6ac48" and v["rating"] == 2 and v["status"] == "NEW"
    assert v["photos"] == 1 and v["link"] == "https://www.ozon.ru/product/1000123456/"
    assert "last_id=017c0d53" in d["more"]
    s = Fake.seen[0]
    assert s["path"] == "/v2/review/list"
    assert s["body"] == {"filters": {"status": "NEW", "sku": [1000123456]}, "limit": 20, "sort_dir": "DESC"}, \
        "у Ozon limit не меньше 20 — просим 20, отдаём сколько просили"


@pytest.mark.parametrize("status", [401, 500])
def test_key_not_leaked_on_errors(env, status):
    Fake.status = status
    r1, r2 = rpc([call("ozon_list_stocks"), call("ozon_list_reviews")], env)
    for r in (r1, r2):
        assert "Ozon ответил" in err(r)


def test_wrong_key_401(env, tmp_path):
    other = tmp_path / "other.token"
    other.write_text(json.dumps({"client_id": CID, "api_key": "test" + "otherkey" + "99999999"}))
    (r,) = rpc([call("ozon_list_prices")], env | {"GAS_OZON_KEY_FILE": str(other)})
    assert "401" in err(r) and "ключ не подходит" in err(r)
    assert "otherkey" not in err(r)


def test_no_key_file(env, tmp_path):
    (r,) = rpc([call("ozon_list_stocks")], env | {"GAS_OZON_KEY_FILE": str(tmp_path / "nope")})
    assert "нет файла ключа" in err(r) and not Fake.seen


def test_bad_key_format(env, tmp_path):
    bad = tmp_path / "bad.token"
    bad.write_text("just-a-key-" + "0000")
    (r,) = rpc([call("ozon_list_stocks")], env | {"GAS_OZON_KEY_FILE": str(bad)})
    assert "client_id" in err(r) and not Fake.seen


def test_propose_no_writes_apply_needs_confirm(env):
    rid = "017c0d1c-66d3-b838-3d29-cf9b95a6ac48"
    (r1,) = rpc([call("ozon_propose_review_comment", {"review_id": rid, "text": "Спасибо, заменим крышку!"})],
                env | {"GAS_OZON_WRITE": "1"})
    p = body(r1)
    assert "черновик" in p["status"] and "заменим крышку" in p["summary"]
    assert not Fake.seen, "propose ничего не шлёт в Ozon"
    (r,) = rpc([call("ozon_apply", {"id": p["id"]})], env | {"GAS_OZON_WRITE": "1"})
    assert "нет подтверждения" in err(r) and not writes()
    c = subprocess.run([sys.executable, str(SERVER), "confirm", p["id"]], capture_output=True, text=True,
                       timeout=30, env=full_env(env))
    assert c.returncode == 2 and "только кнопкой «Да» в панели" in c.stderr      # команды подтверждения больше нет
    panel_stub.grant("ozon", p["id"])                                           # «Да» человека — в панели
    (r,) = rpc([call("ozon_apply", {"id": p["id"]})], env)                  # GAS_OZON_WRITE не задан = 0
    assert "запись выключена" in err(r) and not writes()


def test_apply_after_confirm_exactly_one_write(env):
    e = env | {"GAS_OZON_WRITE": "1"}
    rid = "017c0d1c-66d3-b838-3d29-cf9b95a6ac48"
    (r1,) = rpc([call("ozon_propose_review_comment", {"review_id": rid, "text": "Спасибо!"})], e)
    pid = body(r1)["id"]
    panel_stub.grant("ozon", pid)
    a1, again = rpc([call("ozon_apply", {"id": pid}), call("ozon_apply", {"id": pid})], e)
    d = body(a1)
    assert "отзыв" in d["done"] and d["comment_id"].startswith("c0ffee00")
    assert "не найден" in err(again), "черновик одноразовый"
    (w,) = writes()
    assert (w["http"], w["path"]) == ("POST", "/v1/review/comment/create")
    assert w["body"] == {"review_id": rid, "text": "Спасибо!", "mark_review_as_processed": True}


def test_propose_validates(env):
    r1, r2 = rpc([call("ozon_propose_review_comment", {"review_id": "../../x", "text": "Спасибо"}),
                  call("ozon_propose_review_comment", {"review_id": "017c0d1c-66d3", "text": "!"})], env)
    assert "review_id" in err(r1) and "от 2 до 3000" in err(r2)
