"""Коннектор MAX (docs/CONNECTORS.md) — настоящим процессом, без сети.

**Не проверено на песочнице.** Fixtures в tests/fixtures/max/ собраны по схеме OpenAPI MAX Bot API v0.0.34
(https://github.com/max-messenger/api-schema, коммит 0016ff3) и https://dev.max.ru/docs-api (сверено 20.11.2026),
данные выдуманные. Песочницы у MAX нет; после появления токена тестового бота ночной конвейер заменит их настоящими
(обезличенными) ответами.
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

import panel_stub  # «Да» человека без настоящей панели
import pytest

from gas_pult.connectors import max_mcp

SERVER = Path(max_mcp.__file__)
FIX = Path(__file__).parent / "fixtures" / "max"
TOKEN = "TESTfakeMAX" + "tokenNOTreal" + "0123456789abcdef"   # заведомо фальшивый, склейкой


class Fake(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []
    status = 200
    chat_status = "active"
    chat_type = "dialog"

    def log_message(self, *a):
        pass

    def _send(self, code: int, data):
        data = dict(data)
        data.pop("_source", None)                            # служебная пометка fixture, у MAX её нет
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _fix(self, name: str) -> dict:
        return json.loads((FIX / name).read_text())

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        auth = self.headers.get("Authorization")
        Fake.seen.append({"http": self.command, "path": u.path, "query": q, "body": body, "auth": auth})
        if auth != TOKEN or TOKEN in self.path:
            return self._send(401, self._fix("error_401.json"))
        if Fake.status != 200:                               # сервис «случайно» повторяет токен в ответе
            return self._send(Fake.status, {"code": "internal", "message": f"token {TOKEN} rejected"})
        if u.path == "/me" and self.command == "GET":
            return self._send(200, self._fix("me.json"))
        if u.path == "/updates" and self.command == "GET":
            return self._send(200, self._fix("updates.json"))
        if u.path.startswith("/chats/") and self.command == "GET":
            r = self._fix("chat_dialog.json")
            r["chat_id"], r["status"], r["type"] = int(u.path.rsplit("/", 1)[1]), Fake.chat_status, Fake.chat_type
            return self._send(200, r)
        if u.path == "/messages" and self.command == "GET":
            return self._send(200, self._fix("messages.json"))
        if u.path.startswith("/messages/") and self.command == "GET":
            return self._send(200, self._fix("message.json"))
        if u.path == "/messages" and self.command == "POST":
            return self._send(200, self._fix("sent.json"))
        return self._send(404, {"code": "not.found", "message": "Resource not found"})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle


@pytest.fixture
def env(tmp_path):
    Fake.seen, Fake.status, Fake.chat_status, Fake.chat_type = [], 200, "active", "dialog"
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    keyfile = tmp_path / "max.token"
    keyfile.write_text(TOKEN + "\n")
    keyfile.chmod(0o600)
    yield {"GAS_MAX_BASE": f"http://127.0.0.1:{srv.server_port}", "GAS_MAX_KEY_FILE": str(keyfile),
           **panel_stub.env(tmp_path)}
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
    assert out[0]["id"] == 0 and out[0]["result"]["serverInfo"]["name"] == "gas-pult-max"
    assert len(out) == len(calls) + 1
    assert TOKEN not in p.stdout and TOKEN not in p.stderr
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
    return [s for s in Fake.seen if s["http"] in ("POST", "PUT", "PATCH", "DELETE")]


def confirm(env: dict, pid: str):
    full = {k: v for k, v in os.environ.items() if not k.startswith("GAS_")} | env
    p = subprocess.run([sys.executable, str(SERVER), "confirm", pid], capture_output=True, text=True,
                       timeout=30, env=full)
    assert p.returncode == 2 and "только кнопкой «Да» в панели" in p.stderr   # команды подтверждения больше нет
    panel_stub.grant(max_mcp.SVC, pid)                                          # «Да» человека — в панели


def test_tools_list(env):
    (r,) = rpc([("tools/list", {})], env)
    names = [t["name"] for t in r["result"]["tools"]]
    assert names == ["max_list_messages", "max_list_history", "max_get_message", "max_get_chat", "max_get_bot",
                     "max_propose_reply", "max_apply"]
    assert all("fn" not in t and t["description"] for t in r["result"]["tools"])


def test_list_messages_reads_without_marker(env):
    (r,) = rpc([call("max_list_messages")], env)
    out = body(r)
    assert out["total"] == 7
    kinds = [m["kind"] for m in out["messages"]]
    assert kinds == ["начал диалог", "новое", "новое", "новое", "изменено", "удалено", "остановил бота"]
    first = out["messages"][1]
    assert first["direction"] == "входящее" and first["chat_id"] == 5550001 and first["message_id"] == "mid.0000aa01"
    assert first["from"]["name"] == "Ирина Тестова" and "горячей воды" in first["text"]
    assert first["date"].startswith("2025-11-")
    assert out["messages"][2]["text"] == "[фото] Протечка в подъезде 2, фото"
    assert out["messages"][3]["direction"] == "исходящее" and out["messages"][3]["reply_to"] == "mid.0000aa01"
    assert out["messages"][0]["payload"] == "kv-12"
    (req,) = Fake.seen
    assert req["http"] == "GET" and req["path"] == "/updates" and req["auth"] == TOKEN
    assert "marker" not in req["query"]                  # без marker MAX ничего не считает подтверждённым
    assert req["query"]["timeout"] == "0" and "message_created" in req["query"]["types"]


def test_list_messages_filters(env):
    r1, r2 = rpc([call("max_list_messages", {"chat_id": -6660001}),
                  call("max_list_messages", {"only_incoming": True, "limit": 2})], env)
    a = body(r1)
    assert a["total"] == 2 and {m["kind"] for m in a["messages"]} == {"изменено", "удалено"}
    b = body(r2)
    assert len(b["messages"]) == 2 and all(m["direction"] == "входящее" for m in b["messages"])
    assert b["total"] == 3 and "more" in b


def test_list_history_and_get(env):
    r1, r2, r3, r4 = rpc([call("max_list_history", {"chat_id": 5550001, "limit": 2, "before": 1763597000000}),
                          call("max_get_message", {"message_id": "mid.0000aa01"}),
                          call("max_get_chat", {"chat_id": 5550001}),
                          call("max_get_bot")], env)
    h = body(r1)
    assert [m["message_id"] for m in h["messages"]] == ["mid.0000aa03", "mid.0000aa01"] and "more" in h
    assert body(r2)["text"].startswith("Добрый день")
    c = body(r3)
    assert c["type"] == "dialog" and c["status"] == "active" and c["dialog_with"]["id"] == 7770001
    b = body(r4)
    assert b["bot"]["username"] == "@puls_uk_test_bot" and b["commands"] == ["start", "zayavka"]
    paths = [(s["path"], s["query"]) for s in Fake.seen]
    assert paths[0] == ("/messages", {"chat_id": "5550001", "count": "2", "before": "1763597000000"})
    assert paths[1][0] == "/messages/mid.0000aa01" and paths[2][0] == "/chats/5550001" and paths[3][0] == "/me"
    assert all(s["auth"] == TOKEN and s["http"] == "GET" for s in Fake.seen)


def test_bad_ids_rejected_without_request(env):
    r1, r2 = rpc([call("max_get_message", {"message_id": "../me"}), call("max_get_chat", {"chat_id": "abc"})], env)
    assert "mid" in err(r1) and "целое" in err(r2)
    assert Fake.seen == []


@pytest.mark.parametrize("status", [401, 403, 500])
def test_key_not_leaked_on_errors(env, status):
    Fake.status = status
    (r,) = rpc([call("max_list_messages")], env)
    text = err(r)
    assert TOKEN not in text and "***" in text and str(status) in text
    if status == 403:
        assert "read_all_messages" in text


def test_wrong_key_401(env, tmp_path):
    bad = tmp_path / "bad.token"
    bad.write_text("WRONGfakeTOKENvalue1234567890\n")
    (r,) = rpc([call("max_get_bot")], env | {"GAS_MAX_KEY_FILE": str(bad)})
    assert "401" in err(r) and "ключ не подходит" in err(r)


def test_malformed_key_file(env, tmp_path):
    bad = tmp_path / "max.token"
    bad.write_text("два слова\n")
    (r,) = rpc([call("max_get_bot")], env | {"GAS_MAX_KEY_FILE": str(bad)})
    assert "одной строкой" in err(r) and Fake.seen == []


def test_no_key_file(env, tmp_path):
    (r,) = rpc([call("max_list_messages")], env | {"GAS_MAX_KEY_FILE": str(tmp_path / "нет.token")})
    assert "нет файла ключа" in err(r) and Fake.seen == []


def test_propose_sends_nothing_and_apply_needs_confirm(env):
    (r,) = rpc([call("max_propose_reply", {"chat_id": 5550001, "text": "Мастер выехал.",
                                           "reply_to": "mid.0000aa01"})], env)
    d = body(r)
    assert d["params"] == {"chat_id": 5550001, "text": "Мастер выехал.", "reply_to": "mid.0000aa01"}
    assert "Ирина Тестова" in d["summary"]
    assert writes() == []                               # propose только читает чат
    pid = d["id"]
    (r,) = rpc([call("max_apply", {"id": pid})], env)   # запись выключена
    assert "запись выключена" in err(r)
    (r,) = rpc([call("max_apply", {"id": pid})], env | {"GAS_MAX_WRITE": "1"})
    assert "нет подтверждения" in err(r)
    assert writes() == []
    confirm(env, pid)
    (r,) = rpc([call("max_apply", {"id": pid})], env | {"GAS_MAX_WRITE": "1"})
    done = body(r)
    assert done["message_id"] == "mid.0000aa04"
    (w,) = writes()
    assert w["path"] == "/messages" and w["query"] == {"chat_id": "5550001"} and w["auth"] == TOKEN
    assert w["body"] == {"text": "Мастер выехал.", "notify": True, "link": {"type": "reply", "mid": "mid.0000aa01"}}
    (r,) = rpc([call("max_apply", {"id": pid})], env | {"GAS_MAX_WRITE": "1"})   # одноразово
    assert "не найден" in err(r) and len(writes()) == 1


@pytest.mark.parametrize(("status", "kind", "word"), [("suspended", "dialog", "остановил"),
                                                       ("removed", "chat", "удалили"),
                                                       ("active", "channel", "канал")])
def test_propose_refused_when_cannot_reply(env, status, kind, word):
    Fake.chat_status, Fake.chat_type = status, kind
    (r,) = rpc([call("max_propose_reply", {"chat_id": 5550001, "text": "Привет"})], env)
    assert word in err(r) and writes() == []


def test_propose_validates(env):
    r1, r2, r3 = rpc([call("max_propose_reply", {"chat_id": 5550001, "text": ""}),
                      call("max_propose_reply", {"chat_id": 5550001, "text": "я" * 4001}),
                      call("max_propose_reply", {"chat_id": 5550001, "text": "ок", "reply_to": "a b"})], env)
    assert "от 1 до 4000" in err(r1) and "от 1 до 4000" in err(r2) and "mid" in err(r3)
    assert Fake.seen == []
