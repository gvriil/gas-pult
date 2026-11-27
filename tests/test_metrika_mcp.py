"""Коннектор Яндекс Метрики (docs/CONNECTORS.md) — настоящим процессом, без сети.

**Не проверено на песочнице** (песочницы у Метрики нет, ключа ещё нет). Fixtures в tests/fixtures/metrika/ собраны по
примерам ответов из документации Метрики (yandex.ru/dev/metrika/ru — через индекс Context7, 22.11.2026), названия,
сайты и цифры выдуманные. Когда появится токен `metrika:read` — заменить ответами настоящего счётчика (обезличить).
Записи у коннектора нет: тест проверяет, что ни один запрос не бывает не-GET.
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

from gas_pult.connectors import metrika_mcp as mk

SERVER = Path(mk.__file__)
FIX = Path(__file__).parent / "fixtures" / "metrika"
TOKEN = "y0_" + "TESTmetrika" + "0123456789abcdef"          # заведомо не настоящий, склейкой — не для сканера
COUNTER = "880000"


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

    @staticmethod
    def _fix(name: str) -> dict:
        d = json.loads((FIX / name).read_text())
        d.pop("_source", None)                           # служебная пометка fixture, у Метрики её нет
        return d

    def _handle(self):
        u = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        Fake.seen.append({"http": self.command, "path": u.path, "q": q, "auth": self.headers.get("Authorization")})
        if self.headers.get("Authorization") != f"OAuth {TOKEN}":
            return self._send(401, {"errors": [{"error_type": "invalid_token",
                                                "message": f"Invalid oauth_token {self.headers.get('Authorization')}"}],
                                    "code": 401, "message": "Invalid oauth_token"})
        if Fake.status != 200:                           # сервис «случайно» повторяет ключ в ответе
            return self._send(Fake.status, {"code": Fake.status, "message": f"internal {TOKEN}"})
        if self.command != "GET":
            return self._send(405, {"code": 405, "message": "write is not expected"})
        if u.path == "/management/v1/counters":
            return self._send(200, self._fix("counters.json"))
        if u.path == f"/management/v1/counter/{COUNTER}/goals":
            return self._send(200, self._fix("goals.json"))
        if u.path == "/stat/v1/data":
            dim, metrics = q.get("dimensions", ""), q.get("metrics", "")
            name = ("days.json" if dim == "ym:s:date" else "sources.json" if dim == "ym:s:lastTrafficSource"
                    else "goals_stat.json" if "goal" in metrics
                    else "summary.json" if q.get("date1") == "2026-11-20" else "summary_prev.json")
            return self._send(200, self._fix(name))
        return self._send(404, {"code": 404, "message": "not found"})

    do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = _handle


@pytest.fixture
def env(tmp_path):
    Fake.seen, Fake.status = [], 200
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    keyfile = tmp_path / "metrika.token"
    keyfile.write_text(json.dumps({"token": TOKEN, "counter": COUNTER}) + "\n")
    keyfile.chmod(0o600)
    yield {"GAS_METRIKA_BASE": f"http://127.0.0.1:{srv.server_port}", "GAS_METRIKA_KEY_FILE": str(keyfile),
           "GAS_CONFIRM_DIR": str(tmp_path / "confirm")}
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
    assert out[0]["id"] == 0 and out[0]["result"]["serverInfo"]["name"] == "gas-pult-metrika"
    assert len(out) == len(calls) + 1
    assert TOKEN not in p.stdout and TOKEN not in p.stderr
    assert not [s for s in Fake.seen if s["http"] != "GET"], "коннектор только читает"
    return out[1:]


def call(name: str, args: dict | None = None) -> tuple[str, dict]:
    return "tools/call", {"name": name, "arguments": args or {}}


def body(resp: dict):
    assert not resp["result"]["isError"], resp["result"]["content"][0]["text"]
    return json.loads(resp["result"]["content"][0]["text"])


def err(resp: dict) -> str:
    assert resp["result"]["isError"]
    return resp["result"]["content"][0]["text"]


def test_tools_list_read_only(env):
    (r,) = rpc([("tools/list", {})], env)
    names = [t["name"] for t in r["result"]["tools"]]
    assert names == ["metrika_list_counters", "metrika_get_summary", "metrika_list_days", "metrika_list_sources",
                     "metrika_list_goals"]
    assert not [n for n in names if "propose" in n or "apply" in n], "записи у коннектора нет"
    assert all("fn" not in t and t["description"] for t in r["result"]["tools"])
    assert not Fake.seen


def test_list_counters(env):
    (r,) = rpc([call("metrika_list_counters", {"limit": 1, "search": "coffee"})], env)
    d = body(r)
    (c,) = d["rows"]
    assert c == {"id": 880000, "name": "Кофейня «Пример»", "site": "coffee-example.ru", "status": "Active",
                 "activity": "medium", "permission": "own", "timezone": "Europe/Moscow",
                 "link": "https://metrika.yandex.ru/dashboard?id=880000"}
    assert d["total"] == 2 and "из 2" in d["more"]
    (s,) = Fake.seen
    assert (s["http"], s["path"]) == ("GET", "/management/v1/counters")
    assert s["auth"] == f"OAuth {TOKEN}", "Метрика: заголовок Authorization: OAuth <токен>, не Bearer"
    assert s["q"] == {"per_page": "1", "search_string": "coffee"}


def test_get_summary_with_previous(env):
    (r,) = rpc([call("metrika_get_summary", {"date_from": "2026-11-20", "date_to": "2026-11-20"})], env)
    d = body(r)
    assert d["counter"] == COUNTER and d["period"] == ["2026-11-20", "2026-11-20"]
    assert (d["visits"], d["users"], d["pageviews"]) == (240, 198, 612)
    assert d["bounce_rate_pct"] == 21.25 and d["new_users_pct"] == 64.14
    assert d["previous"]["period"] == ["2026-11-19", "2026-11-19"] and d["previous"]["visits"] == 200
    assert d["change_pct"] == {"visits": 20.0, "users": 10.0, "pageviews": 2.0}
    assert "sampled" not in d, "выборка была только в прошлом периоде"
    cur, prev = Fake.seen
    assert cur["path"] == prev["path"] == "/stat/v1/data"
    assert cur["q"] == {"ids": COUNTER, "metrics": ",".join(m for _, m in mk.SUMMARY), "date1": "2026-11-20",
                        "date2": "2026-11-20", "accuracy": "full", "lang": "ru"}
    assert (prev["q"]["date1"], prev["q"]["date2"]) == ("2026-11-19", "2026-11-19")


def test_list_days(env):
    (r,) = rpc([call("metrika_list_days", {"date_from": "2026-11-18", "date_to": "2026-11-20", "counter": "880000"})],
               env)
    d = body(r)
    assert [x["date"] for x in d["rows"]] == ["2026-11-18", "2026-11-19", "2026-11-20"]
    assert d["rows"][2] == {"date": "2026-11-20", "visits": 240, "users": 198, "pageviews": 612}
    assert d["total"] == {"visits": 620, "users": 489, "pageviews": 1622}
    q = Fake.seen[0]["q"]
    assert q["dimensions"] == "ym:s:date" and q["sort"] == "ym:s:date" and q["ids"] == COUNTER


def test_list_sources(env):
    (r,) = rpc([call("metrika_list_sources", {"date_from": "2026-11-14", "date_to": "2026-11-20", "limit": 3})], env)
    d = body(r)
    assert d["rows"][0] == {"source": "Переходы из поисковых систем", "source_id": "organic", "visits": 820,
                            "users": 700, "bounce_rate_pct": 18.5}
    assert d["rows"][1]["bounce_rate_pct"] == 30.24
    assert "скрыта" in d["privacy"]
    q = Fake.seen[0]["q"]
    assert q["dimensions"] == "ym:s:lastTrafficSource" and q["sort"] == "-ym:s:visits" and q["limit"] == "3"


def test_list_goals(env):
    (r,) = rpc([call("metrika_list_goals", {"date_from": "2026-11-14", "date_to": "2026-11-20"})], env)
    d = body(r)
    assert d["rows"] == [{"id": 30606879, "name": "Заявка с сайта", "type": "action", "reaches": 42,
                          "conversion_pct": 3.04},
                         {"id": 30606884, "name": "Клик по телефону", "type": "phone", "reaches": 17,
                          "conversion_pct": 1.23}]
    g, s = Fake.seen
    assert g["path"] == f"/management/v1/counter/{COUNTER}/goals"
    assert s["q"]["metrics"] == ("ym:s:goal30606879reaches,ym:s:goal30606879conversionRate,"
                                 "ym:s:goal30606884reaches,ym:s:goal30606884conversionRate")


def test_plain_token_needs_counter(env, tmp_path):
    plain = tmp_path / "plain.token"
    plain.write_text(TOKEN + "\n")
    e = env | {"GAS_METRIKA_KEY_FILE": str(plain)}
    r1, r2 = rpc([call("metrika_get_summary"), call("metrika_list_counters")], e)
    assert "не указан счётчик" in err(r1)
    assert body(r2)["rows"], "список счётчиков работает и без counter"
    assert len(Fake.seen) == 1


@pytest.mark.parametrize(("args", "msg"), [({"date_from": "вчера"}, "ГГГГ-ММ-ДД"),
                                           ({"date_from": "2026-11-20", "date_to": "2026-11-10"}, "раньше"),
                                           ({"date_from": "2024-01-01", "date_to": "2026-01-01"}, "не больше"),
                                           ({"counter": "../../x"}, "цифрами")])
def test_bad_args_no_request(env, args, msg):
    (r,) = rpc([call("metrika_get_summary", args)], env)
    assert msg in err(r) and not Fake.seen


@pytest.mark.parametrize("status", [401, 500])
def test_key_not_leaked_on_errors(env, status):
    Fake.status = status
    r1, r2 = rpc([call("metrika_list_counters"), call("metrika_get_summary")], env)
    for r in (r1, r2):
        assert "Яндекс Метрика ответил" in err(r)


def test_wrong_key_401(env, tmp_path):
    other = tmp_path / "other.token"
    other.write_text(json.dumps({"token": "y0_" + "otherkey" + "99999999", "counter": COUNTER}))
    (r,) = rpc([call("metrika_list_counters")], env | {"GAS_METRIKA_KEY_FILE": str(other)})
    assert "401" in err(r) and "ключ не подходит" in err(r)
    assert "otherkey" not in err(r)


def test_no_key_file(env, tmp_path):
    (r,) = rpc([call("metrika_list_counters")], env | {"GAS_METRIKA_KEY_FILE": str(tmp_path / "nope")})
    assert "нет файла ключа" in err(r) and not Fake.seen


def test_bad_key_format(env, tmp_path):
    bad = tmp_path / "bad.token"
    bad.write_text('{"oauth": "' + "x" * 12 + '"}')
    (r,) = rpc([call("metrika_list_counters")], env | {"GAS_METRIKA_KEY_FILE": str(bad)})
    assert "token" in err(r) and not Fake.seen
