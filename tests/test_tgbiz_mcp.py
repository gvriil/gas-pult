"""Коннектор Telegram Business (docs/CONNECTORS.md) — настоящим процессом, без сети.

**Не проверено на живом боте.** Fixtures в tests/fixtures/tgbiz/ собраны по описанию типов Bot API 10.4
(https://core.telegram.org/bots/api, сверено 16.11.2026), данные выдуманные. После появления токена тестового бота
ночной конвейер заменит их настоящими (обезличенными) ответами.
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

from gas_pult.connectors import tgbiz_mcp

SERVER = Path(tgbiz_mcp.__file__)
FIX = Path(__file__).parent / "fixtures" / "tgbiz"
TOKEN = "1234567" + ":" + "TESTfakeTOKENnotREAL" + "0123456789abcdefXYZ"   # заведомо фальшивый, склейкой


class Fake(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []
    status = 200
    rights: ClassVar[dict] = {}

    def log_message(self, *a):
        pass

    def _send(self, code: int, data):
        data = dict(data)
        data.pop("_source", None)                            # служебная пометка fixture, у Telegram её нет
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
        prefix, _, method = u.path.rpartition("/")
        Fake.seen.append({"http": self.command, "method": method, "query": q, "body": body,
                          "token_ok": prefix == f"/bot{TOKEN}"})
        if prefix != f"/bot{TOKEN}":
            return self._send(401, self._fix("error_401.json"))
        if Fake.status != 200:                               # сервис «случайно» повторяет токен в ответе
            return self._send(Fake.status, {"ok": False, "error_code": Fake.status,
                                            "description": f"Internal: token {TOKEN} rejected"})
        if method == "getMe":
            return self._send(200, self._fix("getme.json"))
        if method == "getUpdates":
            return self._send(200, self._fix("updates.json"))
        if method == "getBusinessConnection":
            r = self._fix("connection.json")
            r["result"]["id"] = q.get("business_connection_id", "")
            r["result"]["rights"] = Fake.rights or r["result"]["rights"]
            return self._send(200, r)
        if method == "sendMessage" and self.command == "POST":
            return self._send(200, self._fix("sent.json"))
        return self._send(404, {"ok": False, "error_code": 404, "description": "Not Found"})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle


@pytest.fixture
def env(tmp_path):
    Fake.seen, Fake.status, Fake.rights = [], 200, {}
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    keyfile = tmp_path / "tg-business-bot.token"
    keyfile.write_text(TOKEN + "\n")
    keyfile.chmod(0o600)
    yield {"GAS_TGBIZ_BASE": f"http://127.0.0.1:{srv.server_port}", "GAS_TGBIZ_KEY_FILE": str(keyfile),
           **panel_stub.env(tmp_path),
           "GAS_TGBIZ_STATE": str(tmp_path / "tgbiz")}          # не журнал живой службы на этой машине
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
    assert out[0]["id"] == 0 and out[0]["result"]["serverInfo"]["name"] == "gas-pult-tgbiz"
    assert len(out) == len(calls) + 1
    assert TOKEN not in p.stdout and TOKEN not in p.stderr
    assert TOKEN.split(":")[1] not in p.stdout and TOKEN.split(":")[1] not in p.stderr
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
    assert p.returncode == 2 and "только кнопкой «Да» в панели" in p.stderr      # команды подтверждения больше нет
    panel_stub.grant("tgbiz", pid)                                              # «Да» человека — в панели


def test_tools_list(env):
    (r,) = rpc([("tools/list", {})], env)
    names = [t["name"] for t in r["result"]["tools"]]
    assert names == ["tgbiz_list_messages", "tgbiz_list_connections", "tgbiz_get_connection", "tgbiz_get_bot",
                     "tgbiz_propose_reply", "tgbiz_propose_note", "tgbiz_apply"]
    assert all("fn" not in t and t["description"] for t in r["result"]["tools"])


def test_list_messages_reads_without_confirming(env):
    (r,) = rpc([call("tgbiz_list_messages")], env)
    out = body(r)
    assert out["total"] == 6
    kinds = [m["kind"] for m in out["messages"]]
    assert kinds == ["новое", "новое", "новое", "изменено", "удалено", "новое"]
    first = out["messages"][0]
    assert first["direction"] == "входящее" and first["chat"]["id"] == 7770001
    assert first["date"].startswith("2025-11-1") and "горячей воды" in first["text"]
    assert out["messages"][1]["text"] == "[фото] Протечка в подъезде 2, фото"
    assert out["messages"][2]["direction"] == "исходящее" and out["messages"][2]["reply_to"] == 41
    assert out["messages"][3]["edited"]
    assert out["messages"][4]["message_ids"] == [42]
    assert out["messages"][5]["text"] == "[голосовое]"
    (s,) = Fake.seen
    assert s["http"] == "GET" and s["method"] == "getUpdates" and s["token_ok"]
    assert "offset" not in s["query"]                        # очередь Telegram не подтверждаем
    assert json.loads(s["query"]["allowed_updates"]) == tgbiz_mcp.BUSINESS_UPDATES
    assert not writes()


def test_list_messages_filters(env):
    r1, r2, r3 = rpc([call("tgbiz_list_messages", {"chat_id": 7770001, "only_incoming": True}),
                      call("tgbiz_list_messages", {"connection_id": "BCtestBBBB0002"}),
                      call("tgbiz_list_messages", {"limit": 2})], env)
    a = body(r1)["messages"]
    assert [m["message_id"] for m in a] == [41, 41] and all(m["direction"] == "входящее" for m in a)
    assert [m["chat"]["name"] for m in body(r2)["messages"]] == ["Олег"]
    c = body(r3)
    assert len(c["messages"]) == 2 and c["total"] == 6 and "последние 2" in c["more"]


def test_list_connections_and_get(env):
    r1, r2 = rpc([call("tgbiz_list_connections"), call("tgbiz_get_connection", {"connection_id": "BCtestBBBB0002"})],
                 env)
    conns = body(r1)["connections"]
    assert [c["id"] for c in conns] == ["BCtestAAAA0001", "BCtestBBBB0002"]
    assert conns[0]["can_reply"] and conns[0]["owner"]["username"] == "@uk_dom_test"
    assert not conns[1]["can_reply"]                          # уточнено getBusinessConnection
    one = body(r2)
    assert one["id"] == "BCtestBBBB0002" and one["enabled"] and one["rights"] == ["can_read_messages"]
    gbc = [s for s in Fake.seen if s["method"] == "getBusinessConnection"]
    assert gbc and all(s["query"]["business_connection_id"] == "BCtestBBBB0002" for s in gbc)
    assert not writes()


def test_get_bot(env):
    (r,) = rpc([call("tgbiz_get_bot")], env)
    out = body(r)
    assert out["bot"]["username"] == "@gas_inbox_test_bot" and out["can_connect_to_business"] and not out["hint"]


@pytest.mark.parametrize("status", [401, 500])
def test_key_not_leaked_on_errors(env, status):
    Fake.status = status
    r1, r2 = rpc([call("tgbiz_list_messages"), call("tgbiz_get_bot")], env)   # rpc() проверяет stdout/stderr
    assert str(status) in err(r1) and str(status) in err(r2)
    if status == 401:
        assert "ключ не подходит" in err(r1)


def test_wrong_token_file(env, tmp_path):
    bad = tmp_path / "bad.token"
    bad.write_text("не токен")
    (r,) = rpc([call("tgbiz_get_bot")], env | {"GAS_TGBIZ_KEY_FILE": str(bad)})
    assert "токен бота одной строкой" in err(r) and not Fake.seen


def test_no_key_file(env, tmp_path):
    (r,) = rpc([call("tgbiz_list_messages")], env | {"GAS_TGBIZ_KEY_FILE": str(tmp_path / "нет.token")})
    assert "нет файла ключа" in err(r) and not Fake.seen


def test_default_key_file_name(env, tmp_path):
    e = {k: v for k, v in env.items() if k != "GAS_TGBIZ_KEY_FILE"} | {"HOME": str(tmp_path / "home")}
    (r,) = rpc([call("tgbiz_get_bot")], e)
    assert "tg-business-bot.token" in err(r)


def test_propose_sends_nothing_and_apply_needs_confirm(env):
    args = {"connection_id": "BCtestAAAA0001", "chat_id": 7770001, "text": "Пётр, мастер выехал.", "reply_to": 41}
    Fake.rights = {"can_reply": True}
    (r,) = rpc([call("tgbiz_propose_reply", args)], env)
    draft = body(r)
    assert draft["params"]["text"] == "Пётр, мастер выехал." and "ждёт подтверждения" in draft["status"]
    assert not writes()
    pid = draft["id"]
    (a1,) = rpc([call("tgbiz_apply", {"id": pid})], env)                         # запись выключена
    assert "запись выключена" in err(a1)
    (a2,) = rpc([call("tgbiz_apply", {"id": pid})], env | {"GAS_TGBIZ_WRITE": "1"})  # нет подтверждения
    assert "нет подтверждения" in err(a2)
    assert not writes()
    confirm(env, pid)
    (a3,) = rpc([call("tgbiz_apply", {"id": pid})], env | {"GAS_TGBIZ_WRITE": "1"})
    done = body(a3)
    assert done["message_id"] == 44
    (w,) = writes()
    assert w["method"] == "sendMessage" and w["body"] == {
        "business_connection_id": "BCtestAAAA0001", "chat_id": 7770001, "text": "Пётр, мастер выехал.",
        "reply_parameters": {"message_id": 41, "allow_sending_without_reply": True}}
    (a4,) = rpc([call("tgbiz_apply", {"id": pid})], env | {"GAS_TGBIZ_WRITE": "1"})  # одноразово
    assert "не найден" in err(a4) and len(writes()) == 1


def test_propose_refused_without_reply_right(env):
    Fake.rights = {"can_read_messages": True}
    (r,) = rpc([call("tgbiz_propose_reply", {"connection_id": "BCtestBBBB0002", "chat_id": 7770003,
                                             "text": "Добрый день"})], env)
    assert "нет права «отвечать»" in err(r) and not writes()


def test_propose_validates(env):
    r1, r2 = rpc([call("tgbiz_propose_reply", {"connection_id": "BCtestAAAA0001", "chat_id": 1, "text": ""}),
                  call("tgbiz_propose_reply", {"connection_id": "a b", "chat_id": 1, "text": "x"})], env)
    assert "1 до 4096" in err(r1) and "connection_id" in err(r2) and not Fake.seen


def test_note_local_without_notion(env, tmp_path):
    """Владелец 16.11: «бот оставляет заметки». Notion не настроен — заметка в локальный файл и напоминание."""
    home = tmp_path / "home"
    e = env | {"HOME": str(home), "GAS_NOTION_KEY_FILE": str(tmp_path / "нет.token")}
    (r,) = rpc([call("tgbiz_propose_note", {"text": "Пётр: оплата до пятницы\nсумма 12 000", "source": "чат 7770001",
                                            "tags": ["оплата"]})], e)
    d = body(r)
    assert d["params"]["title"] == "Пётр: оплата до пятницы" and "локальный файл" in d["summary"]
    (a1,) = rpc([call("tgbiz_apply", {"id": d["id"]})], e | {"GAS_TGBIZ_WRITE": "1"})
    assert "нет подтверждения" in err(a1)                               # без человека — ничего не сохранено
    assert not (home / ".local/state/gas-pult/notes").exists()
    confirm(e, d["id"])
    (a2,) = rpc([call("tgbiz_apply", {"id": d["id"]})], e | {"GAS_TGBIZ_WRITE": "1"})
    done = body(a2)
    assert done["saved"] == "local" and "notion.token" in done["remind"]
    text = Path(done["path"]).read_text(encoding="utf-8")
    assert "Пётр: оплата до пятницы" in text and "сумма 12 000" in text and "Источник: чат 7770001" in text
    assert oct(Path(done["path"]).stat().st_mode)[-3:] == "600"


def test_note_to_notion_and_fallback(tmp_path, monkeypatch):
    from gas_pult.connectors import _core
    tok = tmp_path / "notion.token"
    tok.write_text("ntn_" + "x" * 40)
    db = "0123456789abcdef0123456789abcdef"
    monkeypatch.setenv("GAS_NOTION_KEY_FILE", str(tok))
    monkeypatch.setenv("GAS_NOTION_NOTES_DB", db)
    monkeypatch.setattr(tgbiz_mcp, "NOTES_DIR", tmp_path / "notes")
    monkeypatch.setattr(tgbiz_mcp, "_SCHEMA", {db: {"Name": {"type": "title", "title": {}}}})
    sent = []
    monkeypatch.setattr(_core, "http", lambda m, url, **k: sent.append((m, url, k)) or {"url": "https://notion.so/x"})
    out = tgbiz_mcp._save_note({"title": "Встреча", "text": "Вторник 10:00", "source": "", "tags": []})
    assert out == {"saved": "notion", "url": "https://notion.so/x"}
    m, url, k = sent[0]
    assert m == "POST" and url.endswith("/v1/pages") and k["body"]["parent"] == {"database_id": db}
    assert k["headers"]["Notion-Version"]
    assert k["body"]["properties"]["Name"]["title"][0]["text"]["content"] == "Встреча"

    def fail(*a, **k):
        raise _core.ToolError("Notion: 401")
    monkeypatch.setattr(_core, "http", fail)                            # Notion не принял — заметка не теряется
    out = tgbiz_mcp._save_note({"title": "Звонок", "text": "перезвонить", "source": "", "tags": []})
    assert out["saved"] == "local" and "401" in out["warning"] and "перезвонить" in Path(out["path"]).read_text()


def test_note_fields_follow_database_schema(tmp_path, monkeypatch):
    """База «Заметки (бот GASTECH Business)», штаб 16.11: заголовок «Заметка», «Текст», «Откуда», «Метки», «Ссылка»."""
    from gas_pult.connectors import _core
    tok = tmp_path / "notion.token"
    tok.write_text("ntn_" + "y" * 40)
    db = "fedcba9876543210fedcba9876543210"
    monkeypatch.setenv("GAS_NOTION_KEY_FILE", str(tok))
    monkeypatch.setenv("GAS_NOTION_NOTES_DB", db)
    monkeypatch.setattr(tgbiz_mcp, "_SCHEMA", {})
    schema = {"Заметка": {"type": "title", "title": {}}, "Текст": {"type": "rich_text", "rich_text": {}},
              "Откуда": {"type": "select", "select": {"options": [{"name": "Личка бота"}, {"name": "Голос"}]}},
              "Метки": {"type": "multi_select", "multi_select": {"options": [{"name": "задача"}, {"name": "идея"}]}},
              "Ссылка": {"type": "url", "url": {}}, "Создано": {"type": "created_time", "created_time": {}}}
    sent = []

    def http(m, url, **k):
        sent.append((m, url, k))
        return {"properties": schema} if m == "GET" else {"url": "https://notion.so/n"}
    monkeypatch.setattr(_core, "http", http)
    for _ in range(2):
        tgbiz_mcp._save_note({"title": "Позвонить Петру", "text": "Позвонить Петру #задача #чужая",
                              "source": "бот", "tags": ["задача", "чужая"], "origin": "Личка бота",
                              "link": "https://t.me/c/1/2"})
    assert [m for m, *_ in sent] == ["GET", "POST", "POST"]                 # схема — один раз
    pr = sent[1][2]["body"]["properties"]
    assert pr["Заметка"]["title"][0]["text"]["content"] == "Позвонить Петру" and "Name" not in pr
    assert pr["Текст"]["rich_text"][0]["text"]["content"].startswith("Позвонить Петру")
    assert pr["Откуда"] == {"select": {"name": "Личка бота"}}
    assert pr["Метки"] == {"multi_select": [{"name": "задача"}]}                # чужой метки в базе нет — не шлём
    assert pr["Ссылка"] == {"url": "https://t.me/c/1/2"} and "Создано" not in pr
    tgbiz_mcp._save_note({"title": "x", "text": "x", "source": "", "tags": [], "origin": "Неизвестно"})
    assert "Откуда" not in sent[-1][2]["body"]["properties"]                   # нет такого варианта — поле пустое
