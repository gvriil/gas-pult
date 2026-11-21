"""Коннектор Битрикс24 (docs/CONNECTORS.md) — настоящим процессом, без сети.

**Не проверено на песочнице:** fixtures в tests/fixtures/bitrix24/ собраны по примерам ответов из официальной
документации REST (github.com/bitrix24/b24restdocs @30861a4), данные выдуманные. После появления вебхука демо-портала
ночной конвейер перезапишет их обезличенными ответами.

У Битрикс24 любой метод вызывается POST на ``/rest/<user>/<код>/<метод>.json`` — поэтому «запись» здесь считается
по имени метода (всё, что не из списка чтения), а не по HTTP-методу.
"""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from gas_pult.connectors import bitrix24_mcp

SERVER = Path(bitrix24_mcp.__file__)
FIX = Path(__file__).parent / "fixtures" / "bitrix24"
CODE = "test" + "hook" + "0123456789abcdef"               # заведомо не настоящий, склейкой — не для сканера
HOOK = f"https://demo-club.bitrix24.ru/rest/7/{CODE}/"
PREFIX = f"/rest/7/{CODE}/"


class Fake(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []
    status = 200

    def log_message(self, *a):
        pass

    def _send(self, code: int, data: dict):
        data.pop("_source", None)                           # служебная пометка fixture, у Битрикс24 её нет
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        method = self.path.removeprefix(PREFIX).removesuffix(".json") if self.path.startswith(PREFIX) else None
        Fake.seen.append({"http": self.command, "path": self.path, "method": method, "body": body,
                          "headers": {k.lower(): v for k, v in self.headers.items()}})
        if Fake.status != 200:                              # сервис «случайно» повторяет вебхук в ответе
            err = json.loads((FIX / "error_401.json").read_text())
            err["error_description"] += f" ({HOOK} {CODE})"
            return self._send(Fake.status, err)
        f = FIX / f"{method}.json"
        if not method or not f.is_file():
            return self._send(404, {"error": "ERROR_METHOD_NOT_FOUND", "error_description": "Method not found!"})
        data = json.loads(f.read_text())
        if method == "crm.lead.list" and (body or {}).get("start"):   # вторая страница
            data["result"] = [data["result"][-1] | {"ID": "5", "TITLE": "Звонок"}]
            data.pop("next")
        self._send(200, data)

    do_GET = do_POST = _handle


@pytest.fixture
def env(tmp_path):
    Fake.seen, Fake.status = [], 200
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    keyfile = tmp_path / "bitrix24.token"
    keyfile.write_text(HOOK + "\n")
    keyfile.chmod(0o600)
    yield {"GAS_BITRIX24_BASE": f"http://127.0.0.1:{srv.server_port}",
           "GAS_BITRIX24_KEY_FILE": str(keyfile), "GAS_CONFIRM_DIR": str(tmp_path / "confirm")}
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
    assert out[0]["id"] == 0 and out[0]["result"]["serverInfo"]["name"] == "gas-pult-bitrix24"
    assert len(out) == len(calls) + 1
    assert CODE not in p.stdout and CODE not in p.stderr
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
    return [s for s in Fake.seen if s["method"] not in bitrix24_mcp.READ]


def test_tools_list(env):
    (r,), _ = rpc([("tools/list", {})], env)
    names = [t["name"] for t in r["result"]["tools"]]
    assert names == ["bitrix24_list_deals", "bitrix24_get_deal", "bitrix24_list_leads", "bitrix24_list_contacts",
                     "bitrix24_list_stages", "bitrix24_list_tasks", "bitrix24_propose_deal_stage", "bitrix24_apply"]
    assert all("fn" not in t and t["description"] for t in r["result"]["tools"])


def test_list_deals(env):
    (r,), _ = rpc([call("bitrix24_list_deals", {"limit": 500, "since": "2026-11-01", "search": "Абонемент",
                                                "stage": "NEW", "category": "0"})], env)
    d = body(r)
    assert d["total"] == 3 and "more" not in d
    o = d["rows"][0]
    assert o["id"] == "41" and o["title"] == "Абонемент семейный — Ивановы" and o["sum"] == 19999.99
    assert o["currency"] == "RUB" and o["stage_id"] == "PREPARATION" and o["closed"] is False
    assert o["link"] == "https://demo-club.bitrix24.ru/crm/deal/details/41/"
    s = Fake.seen[0]
    assert s["http"] == "POST" and s["path"] == PREFIX + "crm.deal.list.json"
    assert s["headers"]["content-type"] == "application/json"
    assert s["body"]["filter"] == {"CLOSED": "N", "STAGE_ID": "NEW", "CATEGORY_ID": "0",
                                   ">=DATE_CREATE": "2026-11-01", "%TITLE": "Абонемент"}
    assert s["body"]["order"] == {"DATE_CREATE": "DESC"} and s["body"]["start"] == 0
    assert "ID" in s["body"]["select"] and len(Fake.seen) == 1


def test_list_deals_bad_date(env):
    (r,), _ = rpc([call("bitrix24_list_deals", {"since": "вчера"})], env)
    assert "ГГГГ-ММ-ДД" in err(r) and not Fake.seen


def test_get_deal(env):
    (r,), _ = rpc([call("bitrix24_get_deal", {"id": " 41 "})], env)
    d = body(r)
    assert d["id"] == "41" and d["contact_id"] == "84" and d["stage_kind"] == "в работе"
    assert d["comments"].startswith("Хотят утренние") and d["source"] == "WEB"
    assert Fake.seen[0]["method"] == "crm.deal.get" and Fake.seen[0]["body"] == {"id": "41"}


def test_get_deal_bad_id(env):
    (r,), _ = rpc([call("bitrix24_get_deal", {"id": "../profile"})], env)
    assert "числовой id" in err(r) and not Fake.seen


def test_list_leads_two_pages(env):
    (r,), _ = rpc([call("bitrix24_list_leads", {"status": "NEW"})], env)
    d = body(r)
    assert [x["id"] for x in d["rows"]] == ["7", "6", "5"] and "more" not in d
    assert d["rows"][0]["name"] == "Анна Смирнова" and d["rows"][0]["has_phone"] is True
    assert d["rows"][0]["link"] == "https://demo-club.bitrix24.ru/crm/lead/details/7/"
    assert [s["body"]["start"] for s in Fake.seen] == [0, 2]
    assert Fake.seen[0]["body"]["filter"] == {"STATUS_ID": "NEW"}


def test_list_leads_more(env):
    (r,), _ = rpc([call("bitrix24_list_leads", {"limit": 1})], env)
    d = body(r)
    assert len(d["rows"]) == 1 and "offset=1" in d["more"] and len(Fake.seen) == 1


def test_list_contacts(env):
    (r,), _ = rpc([call("bitrix24_list_contacts", {"phone": "+79990000001"})], env)
    d = body(r)
    assert d["rows"][0] == {"id": "84", "name": "Мария Иванова", "phones": ["+79990000001"],
                            "emails": ["ivanova@example.com"], "company_id": None, "responsible_id": "1",
                            "created": "2026-11-13T00:00:00+03:00",
                            "link": "https://demo-club.bitrix24.ru/crm/contact/details/84/"}
    assert Fake.seen[0]["body"]["filter"] == {"PHONE": "+79990000001"}


def test_list_stages(env):
    (r1, r2), _ = rpc([call("bitrix24_list_stages"), call("bitrix24_list_stages", {"category": "3"})], env)
    d = body(r1)
    assert [s["stage_id"] for s in d["stages"]] == ["NEW", "PREPARATION", "EXECUTING", "WON", "LOSE"]
    assert d["stages"][3]["kind"] == "финальный: успех" and d["stages"][4]["kind"] == "финальный: провал"
    assert Fake.seen[0]["body"]["filter"] == {"ENTITY_ID": "DEAL_STAGE"}
    assert Fake.seen[1]["body"]["filter"] == {"ENTITY_ID": "DEAL_STAGE_3"}
    body(r2)


def test_list_tasks(env):
    (r1, r2), _ = rpc([call("bitrix24_list_tasks", {"responsible_id": "6"}),
                       call("bitrix24_list_tasks", {"overdue": True})], env)
    d = body(r1)
    t = d["rows"][0]
    assert t["id"] == "8017" and t["status"] == "выполняется" and t["responsible"] == "Ольга Менеджерова"
    assert t["high_priority"] is True and t["crm"] == ["D_41"]
    assert d["rows"][1]["status"] == "ждёт выполнения"
    assert Fake.seen[0]["method"] == "tasks.task.list"
    assert Fake.seen[0]["body"]["filter"] == {"<REAL_STATUS": 5, "RESPONSIBLE_ID": "6"}
    assert Fake.seen[0]["body"]["order"] == {"DEADLINE": "ASC"}
    assert Fake.seen[1]["body"]["filter"] == {"STATUS": -1}
    body(r2)


def test_key_never_leaks_on_error(env):
    for code in (401, 500):
        Fake.status = code
        (r,), _ = rpc([call("bitrix24_list_deals")], env)      # rpc сам проверяет stdout/stderr
        t = err(r)
        assert str(code) in t and "***" in t and CODE not in t and "demo-club.bitrix24.ru/rest" not in t


def test_401_hint(env):
    Fake.status = 401
    (r,), _ = rpc([call("bitrix24_list_leads")], env)
    assert "ключ не подходит" in err(r) and "INVALID_CREDENTIALS" in err(r)


def test_no_key_file(env):
    (r,), _ = rpc([call("bitrix24_list_deals")], env | {"GAS_BITRIX24_KEY_FILE": "/nonexistent/bitrix24.token"})
    assert "нет файла ключа" in err(r) and "docs/connectors/bitrix24.md" in err(r)
    assert not Fake.seen


def test_bad_key_format(env, tmp_path):
    bad = tmp_path / "bad.token"
    bad.write_text("просто-токен-" + CODE)
    (r,), _ = rpc([call("bitrix24_list_deals")], env | {"GAS_BITRIX24_KEY_FILE": str(bad)})
    assert "адрес входящего вебхука" in err(r) and not Fake.seen


def test_write_only_after_human(env):
    (p,), _ = rpc([call("bitrix24_propose_deal_stage", {"id": "41", "stage": "в работе"})], env)
    d = body(p)
    assert d["params"] == {"deal_id": "41", "stage_id": "EXECUTING", "from_stage_id": "PREPARATION"}
    assert "«Подготовка договора» → «В работе»" in d["summary"]
    assert not writes(), "propose не должен ничего писать в Битрикс24"
    # без флага записи
    (a,), _ = rpc([call("bitrix24_apply", {"id": d["id"]})], env)
    assert "запись выключена" in err(a)
    # с флагом, но без подтверждения человека
    (a,), _ = rpc([call("bitrix24_apply", {"id": d["id"]})], env | {"GAS_BITRIX24_WRITE": "1"})
    assert "нет подтверждения" in err(a) and not writes()
    # человек подтвердил (CLI пульта) — ровно один вызов записи
    full = {k: v for k, v in os.environ.items() if not k.startswith("GAS_")} | env
    c = subprocess.run([sys.executable, str(SERVER), "confirm", d["id"]], capture_output=True, text=True, env=full)
    assert c.returncode == 0, c.stderr
    (a,), _ = rpc([call("bitrix24_apply", {"id": d["id"]})], env | {"GAS_BITRIX24_WRITE": "1"})
    assert "В работе" in body(a)["done"]
    w = writes()
    assert len(w) == 1 and w[0]["method"] == "crm.deal.update"
    assert w[0]["body"] == {"id": "41", "fields": {"STAGE_ID": "EXECUTING"}}
    # повторно — нельзя
    (a,), _ = rpc([call("bitrix24_apply", {"id": d["id"]})], env | {"GAS_BITRIX24_WRITE": "1"})
    assert "не найден" in err(a) and len(writes()) == 1


def test_propose_unknown_or_same_stage(env):
    (r1, r2), _ = rpc([call("bitrix24_propose_deal_stage", {"id": "41", "stage": "Улетела"}),
                       call("bitrix24_propose_deal_stage", {"id": "41", "stage": "PREPARATION"})], env)
    assert "нет стадии «Улетела»" in err(r1) and "Сделка успешна (WON)" in err(r1)
    assert "менять нечего" in body(r2)["status"]
    assert not writes()


def test_throttle_two_per_second():
    assert (bitrix24_mcp.THROTTLE.n, bitrix24_mcp.THROTTLE.per) == (2, 1.0)
