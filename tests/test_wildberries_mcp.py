"""Коннектор Wildberries (docs/CONNECTORS.md) — настоящим процессом, без сети.

**Не проверено на песочнице.** Fixtures в tests/fixtures/wildberries/ собраны по примерам ответов из OpenAPI WB
(dev.wildberries.ru/api/swagger/yaml/ru/09-communications.yaml, 02-items.yaml, 12-reports.yaml — скачаны 18.11.2026),
тексты и названия выдуманные. Когда появится тестовый токен — заменить ответами песочницы.
"""

import base64
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

from gas_pult.connectors import wildberries_mcp as wb

SERVER = Path(wb.__file__)
FIX = Path(__file__).parent / "fixtures" / "wildberries"
KEY = "test" + "wbtoken" + "0123456789abcdef"              # заведомо не настоящий, склейкой — не для сканера
WRITES = {"POST", "PUT", "PATCH", "DELETE"}


def jwt(payload: dict) -> str:
    enc = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return "eyJhbGciOiJFUzI1NiJ9." + enc + ".sig" + "nature"


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

    def _fix(self, name: str):
        d = json.loads((FIX / name).read_text())
        d.pop("_source", None)                               # служебная пометка fixture, у WB её нет
        return d.pop("_body", d)

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        u = urllib.parse.urlsplit(self.path)
        Fake.seen.append({"http": self.command, "path": u.path, "query": dict(urllib.parse.parse_qsl(u.query)),
                          "body": body, "auth": self.headers.get("Authorization")})
        if self.headers.get("Authorization") != KEY:
            return self._send(401, {"title": "unauthorized", "detail": f"token {self.headers.get('Authorization')}"})
        if Fake.status != 200:                               # сервис «случайно» повторяет ключ в ответе
            return self._send(Fake.status, {"title": "error", "detail": f"bad token {KEY}"})
        routes = {("GET", "/api/v1/feedbacks"): "feedbacks.json", ("GET", "/api/v1/questions"): "questions.json",
                  ("GET", "/api/v2/list/goods/filter"): "prices.json",
                  ("GET", "/api/v1/supplier/orders"): "orders.json"}
        if (self.command, u.path) in routes:
            return self._send(200, self._fix(routes[(self.command, u.path)]))
        if (self.command, u.path) in {("POST", "/api/v1/feedbacks/answer"), ("PATCH", "/api/v1/questions")}:
            return self._send(204)
        return self._send(404, {"title": "not found", "detail": self.path})

    do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = _handle


@pytest.fixture
def env(tmp_path):
    Fake.seen, Fake.status = [], 200
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    keyfile = tmp_path / "wildberries.token"
    keyfile.write_text(KEY + "\n")
    keyfile.chmod(0o600)
    yield {"GAS_WILDBERRIES_BASE": f"http://127.0.0.1:{srv.server_port}",
           "GAS_WILDBERRIES_KEY_FILE": str(keyfile), "GAS_CONFIRM_DIR": str(tmp_path / "confirm"),
           "GAS_WILDBERRIES_ENV": "prod"}
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
    assert out[0]["id"] == 0 and out[0]["result"]["serverInfo"]["name"] == "gas-pult-wildberries"
    assert len(out) == len(calls) + 1
    assert KEY not in p.stdout and KEY not in p.stderr
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
    return [s for s in Fake.seen if s["http"] in WRITES]


def test_tools_list(env):
    (r,) = rpc([("tools/list", {})], env)
    names = [t["name"] for t in r["result"]["tools"]]
    assert names == ["wildberries_list_feedbacks", "wildberries_list_questions", "wildberries_list_prices",
                     "wildberries_list_orders", "wildberries_propose_feedback_answer",
                     "wildberries_propose_question_answer", "wildberries_apply"]
    assert all("fn" not in t and t["description"] for t in r["result"]["tools"])
    assert not Fake.seen


def test_list_feedbacks(env):
    (r,) = rpc([call("wildberries_list_feedbacks", {"limit": 2, "nm_id": 987654321, "date_from": "2026-11-01"})], env)
    d = body(r)
    assert d["среда"] == "боевой кабинет WB" and d["unanswered_total"] == 2 and d["answered_total"] == 1000
    f = d["rows"][0]
    assert f["id"] == "YX52RZEBhH9mrcYdEJuD" and f["rating"] == 2 and f["answer"] is None
    assert f["text"] == "После стирки появились катышки Плюсы: Мягкий Минусы: Катышки"
    assert f["article"] == "PL-150" and f["photos"] == 1 and f["video"] is False
    assert f["link"] == "https://www.wildberries.ru/catalog/987654321/detail.aspx"
    assert d["rows"][1]["video"] is True and "Покупатель" not in json.dumps(d, ensure_ascii=False)
    assert "skip=2" in d["more"]
    (s,) = Fake.seen
    assert s["auth"] == KEY, "WB ждёт токен в Authorization без «Bearer»"
    assert s["path"] == "/api/v1/feedbacks"
    assert s["query"] == {"isAnswered": "false", "take": "2", "skip": "0", "order": "dateDesc",
                          "nmId": "987654321", "dateFrom": "1793480400"}   # 2026-11-01 00:00 МСК


def test_list_questions_answered(env):
    (r,) = rpc([call("wildberries_list_questions", {"answered": True, "limit": 500})], env)
    d = body(r)
    q = d["rows"][0]
    assert q["id"] == "2ncBtX4B9I0UHoornoqG" and q["text"].startswith("Можно стирать") and q["viewed"] is False
    assert "more" not in d
    assert Fake.seen[0]["path"] == "/api/v1/questions"
    assert Fake.seen[0]["query"] == {"isAnswered": "true", "take": "100", "skip": "0", "order": "dateDesc"}


def test_list_prices(env):
    (r,) = rpc([call("wildberries_list_prices", {"limit": 5, "offset": 10})], env)
    d = body(r)
    a, b = d["rows"]
    assert a == {"nm_id": 987654321, "article": "PL-150", "currency": "RUB", "price": 2490, "discount_pct": 30,
                 "price_with_discount": 1743, "club_discount_pct": 5, "club_price": 1655.85,
                 "link": "https://www.wildberries.ru/catalog/987654321/detail.aspx"}
    assert [s["size"] for s in b["sizes"]] == ["42", "48"], "разные цены по размерам — показать все"
    assert Fake.seen[0]["path"] == "/api/v2/list/goods/filter"
    assert Fake.seen[0]["query"] == {"limit": "5", "offset": "10"}


def test_list_orders(env):
    (r,) = rpc([call("wildberries_list_orders", {"date_from": "2026-11-17", "limit": 2})], env)
    d = body(r)
    assert d["total"] == 3 and d["cancelled"] == 1 and d["sum_price_with_discount"] == 1743 + 1113
    assert [o["srid"] for o in d["rows"]] == ["11.test0002.3.0", "11.test0003.3.0"], "свежие сверху"
    assert d["rows"][1]["cancelled"] is True and "из 3" in d["more"]
    assert Fake.seen[0]["path"] == "/api/v1/supplier/orders"
    assert Fake.seen[0]["query"] == {"dateFrom": "2026-11-17T00:00:00", "flag": "0"}


def test_bad_date_no_request(env):
    (r,) = rpc([call("wildberries_list_orders", {"date_from": "вчера"})], env)
    assert "ГГГГ-ММ-ДД" in err(r) and not Fake.seen


@pytest.mark.parametrize("status", [401, 500])
def test_key_not_leaked_on_errors(env, status):
    Fake.status = status
    r1, r2 = rpc([call("wildberries_list_feedbacks"), call("wildberries_list_prices")], env)
    for r in (r1, r2):
        assert "Wildberries ответил" in err(r)


def test_wrong_key_401(env, tmp_path):
    other = tmp_path / "other.token"
    other.write_text("test" + "otherkey" + "99999999")
    (r,) = rpc([call("wildberries_list_feedbacks")], env | {"GAS_WILDBERRIES_KEY_FILE": str(other)})
    assert "401" in err(r) and "ключ не подходит" in err(r)
    assert "otherkey" not in err(r)


def test_no_key_file(env, tmp_path):
    (r,) = rpc([call("wildberries_list_feedbacks")], env | {"GAS_WILDBERRIES_KEY_FILE": str(tmp_path / "nope")})
    assert "нет файла ключа" in err(r) and not Fake.seen


def test_propose_no_writes_apply_needs_confirm(env):
    r1, r2 = rpc([call("wildberries_propose_feedback_answer", {"id": "YX52RZEBhH9mrcYdEJuD", "text": "Спасибо!"}),
                  call("wildberries_propose_question_answer", {"id": "2ncBtX4B9I0UHoornoqG", "text": "Да, при 40°"})],
                 env | {"GAS_WILDBERRIES_WRITE": "1"})
    p1 = body(r1)
    assert "Да, при 40°" in body(r2)["summary"]
    assert "черновик" in p1["status"] and "Спасибо!" in p1["summary"]
    assert not Fake.seen, "propose ничего не шлёт в WB"
    (r,) = rpc([call("wildberries_apply", {"id": p1["id"]})], env | {"GAS_WILDBERRIES_WRITE": "1"})
    assert "нет подтверждения" in err(r) and not writes()
    c = subprocess.run([sys.executable, str(SERVER), "confirm", p1["id"]], capture_output=True, text=True,
                       timeout=30, env=full_env(env))
    assert c.returncode == 0, c.stderr
    (r,) = rpc([call("wildberries_apply", {"id": p1["id"]})], env)           # GAS_WILDBERRIES_WRITE не задан = 0
    assert "запись выключена" in err(r) and not writes()


def test_apply_after_confirm_exactly_one_write(env):
    e = env | {"GAS_WILDBERRIES_WRITE": "1"}
    r1, r2 = rpc([call("wildberries_propose_feedback_answer", {"id": "YX52RZEBhH9mrcYdEJuD", "text": "Спасибо!"}),
                  call("wildberries_propose_question_answer", {"id": "2ncBtX4B9I0UHoornoqG", "text": "Да, при 40°"})],
                 e)
    ids = [body(r1)["id"], body(r2)["id"]]
    for pid in ids:
        subprocess.run([sys.executable, str(SERVER), "confirm", pid], check=True, capture_output=True, timeout=30,
                       env=full_env(e))
    a1, a2, again = rpc([call("wildberries_apply", {"id": ids[0]}), call("wildberries_apply", {"id": ids[1]}),
                         call("wildberries_apply", {"id": ids[0]})], e)
    assert "отзыв" in body(a1)["done"] and "вопрос" in body(a2)["done"]
    assert "не найден" in err(again), "черновик одноразовый"
    w = writes()
    assert [(x["http"], x["path"]) for x in w] == [("POST", "/api/v1/feedbacks/answer"), ("PATCH", "/api/v1/questions")]
    assert w[0]["body"] == {"id": "YX52RZEBhH9mrcYdEJuD", "text": "Спасибо!"}
    assert w[1]["body"] == {"id": "2ncBtX4B9I0UHoornoqG", "answer": {"text": "Да, при 40°"}, "state": "wbRu"}


def test_propose_validates(env):
    r1, r2 = rpc([call("wildberries_propose_feedback_answer", {"id": "../../x", "text": "Спасибо"}),
                  call("wildberries_propose_feedback_answer", {"id": "YX52RZEBhH9mrcYdEJuD", "text": "!"})], env)
    assert "id" in err(r1) and "от 2 до 5000" in err(r2)


def test_env_from_token(monkeypatch):
    monkeypatch.delenv("GAS_WILDBERRIES_ENV", raising=False)
    assert wb._env(jwt({"acc": 2, "t": True})) == "sandbox"
    assert wb._env(jwt({"acc": 3, "for": "self", "t": False})) == "prod"
    assert wb._env("not-a-jwt") == "sandbox"
    monkeypatch.setenv("GAS_WILDBERRIES_ENV", "prod")
    assert wb._env(jwt({"t": True})) == "prod"


def test_hosts(monkeypatch):
    monkeypatch.delenv("GAS_WILDBERRIES_BASE", raising=False)
    assert wb._base("feedbacks", "sandbox") == "https://feedbacks-api-sandbox.wildberries.ru"
    assert wb._base("prices", "sandbox") == "https://discounts-prices-api-sandbox.wildberries.ru"
    assert wb._base("statistics", "prod") == "https://statistics-api.wildberries.ru"
    with pytest.raises(wb._core.ToolError, match="нет песочницы"):
        wb._base("statistics", "sandbox")
