"""Коннектор календаря CalDAV / iCal (docs/CONNECTORS.md) — настоящим процессом, без сети.

**Не проверено на реальном календаре:** события в tests/fixtures/calendar/ выдуманные, ответы CalDAV построены по
RFC 4791 (calendar-query, calendar-home-set) и RFC 5397 (current-user-principal). Фейковый сервер ниже отвечает как
CalDAV-сервер с одним аккаунтом (календарь событий, календарь задач, входящие) и как ссылка iCal; при ошибке входа
«случайно» повторяет пароль — проверяем, что ни пароль, ни секретная ссылка не попадают в stdout и stderr.
"""

import base64
import json
import os
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from zoneinfo import ZoneInfo

import pytest

from gas_pult.connectors import calendar_mcp as cal

SERVER = Path(cal.__file__)
FIX = Path(__file__).parent / "fixtures" / "calendar"
PW = "test" + "-cal-" + "pass0123456789"                # заведомо не настоящий, склейкой — не для сканера
USER = "uk-dom@example.ru"
SECRET = "/ical/" + "s3cr3t" + "token42/basic.ics"     # «секретная ссылка» фейкового сервера
MSK = ZoneInfo("Europe/Moscow")
WORK = "/calendars/uk-dom/work/"


def _ms(*responses: str) -> bytes:
    return ('<?xml version="1.0" encoding="utf-8"?><d:multistatus xmlns:d="DAV:" '
            'xmlns:c="urn:ietf:params:xml:ns:caldav">' + "".join(responses) + "</d:multistatus>").encode()


def _resp(href: str, prop: str) -> str:
    return (f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>{prop}</d:prop>"
            "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")


class DAV(BaseHTTPRequestHandler):
    """CalDAV: PROPFIND (корень → владелец → домашняя папка → календари), REPORT, GET, PUT; и ссылка iCal."""

    seen: ClassVar[list] = []
    mode = "ok"                                         # ok | badauth
    events: ClassVar[dict] = {}

    def log_message(self, *a):
        pass

    def send(self, code: int, body: bytes = b"", ctype: str = "application/xml; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> str:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode() if n else ""

    def _auth(self, body: str) -> bool:
        DAV.seen.append({"m": self.command, "path": self.path, "depth": self.headers.get("Depth"), "body": body,
                         "auth": self.headers.get("Authorization"), "inm": self.headers.get("If-None-Match")})
        want = "Basic " + base64.b64encode(f"{USER}:{PW}".encode()).decode()
        if DAV.mode == "badauth" or self.headers.get("Authorization") != want:
            self.send(401, f"Unauthorized: {USER} / {PW}".encode(), "text/plain")
            return False
        return True

    def do_PROPFIND(self):
        body = self._body()
        if not self._auth(body):
            return
        if self.path == "/.well-known/caldav":
            return self.send(301, extra={"Location": "/"})
        if self.path == "/":
            return self.send(207, _ms(_resp("/", "<d:current-user-principal><d:href>/principals/uk-dom/</d:href>"
                                                 "</d:current-user-principal><d:resourcetype><d:collection/>"
                                                 "</d:resourcetype>")))
        if self.path == "/principals/uk-dom/":
            return self.send(207, _ms(_resp(self.path, "<c:calendar-home-set><d:href>/calendars/uk-dom/</d:href>"
                                                       "</c:calendar-home-set>")))
        if self.path == "/calendars/uk-dom/":
            cal_t = "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
            return self.send(207, _ms(
                _resp(self.path, "<d:resourcetype><d:collection/></d:resourcetype>"),
                _resp(WORK, cal_t + '<d:displayname>Работа</d:displayname><c:supported-calendar-component-set>'
                                    '<c:comp name="VEVENT"/></c:supported-calendar-component-set>'),
                _resp("/calendars/uk-dom/todo/", cal_t + '<d:displayname>Дела</d:displayname>'
                                                         '<c:supported-calendar-component-set><c:comp name="VTODO"/>'
                                                         '</c:supported-calendar-component-set>'),
                _resp("/calendars/uk-dom/inbox/", "<d:resourcetype><d:collection/><c:schedule-inbox/>"
                                                  "</d:resourcetype>")))
        self.send(404)

    def do_REPORT(self):
        body = self._body()
        if not self._auth(body):
            return
        if self.path != WORK or "calendar-query" not in body or "time-range" not in body:
            return self.send(400)
        data = [_resp(WORK + n, f'<d:getetag>"{i}"</d:getetag><c:calendar-data>'
                                f'{t.replace("&", "&amp;").replace("<", "&lt;")}</c:calendar-data>')
                for i, (n, t) in enumerate(sorted(DAV.events.items()))]
        self.send(207, _ms(*data))

    def do_GET(self):
        if self.path == SECRET:                         # ссылка iCal — без пароля
            DAV.seen.append({"m": "GET", "path": "<secret>", "auth": self.headers.get("Authorization")})
            return self.send(200, (FIX / "feed.ics").read_bytes(), "text/calendar; charset=utf-8")
        if not self._auth(""):
            return
        name = self.path.removeprefix(WORK)
        if self.path.startswith(WORK) and name in DAV.events:
            return self.send(200, DAV.events[name].encode(), "text/calendar; charset=utf-8")
        self.send(404, b"not found")

    def do_PUT(self):
        body = self._body()
        if not self._auth(body):
            return
        name = self.path.removeprefix(WORK)
        if self.headers.get("If-None-Match") == "*" and name in DAV.events:
            return self.send(412, b"exists")
        DAV.events[name] = body
        self.send(201)


WRITES = ("PUT", "DELETE", "POST", "PATCH", "MOVE", "COPY", "PROPPATCH", "MKCALENDAR")


def writes() -> list:
    return [s for s in DAV.seen if s["m"] in WRITES]


@pytest.fixture
def env(tmp_path):
    DAV.seen, DAV.mode = [], "ok"
    DAV.events = {p.name: p.read_text() for p in (FIX / "work").glob("*.ics")}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), DAV)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    keys = tmp_path / "keys"
    keys.mkdir()
    for name, cfg in (("yandex", {"kind": "caldav", "url": base + "/", "user": USER, "app_password": PW}),
                      ("family", {"kind": "ics", "url": base + SECRET})):
        f = keys / f"calendar-{name}.json"
        f.write_text(json.dumps(cfg))
        f.chmod(0o600)
    yield {"GAS_CAL_KEY_DIR": str(keys), "GAS_CONFIRM_DIR": str(tmp_path / "confirm"), "GAS_CAL_TZ": "Europe/Moscow",
           "_base": base}
    srv.shutdown()
    srv.server_close()


def run(args: list[str], env: dict, stdin: str = "") -> subprocess.CompletedProcess:
    full = {k: v for k, v in os.environ.items()
            if not k.startswith("GAS_") and k not in ("OPENROUTER_MODEL", "ANTHROPIC_MODEL")}
    full |= {k: v for k, v in env.items() if not k.startswith("_")}
    p = subprocess.run([sys.executable, str(SERVER), *args], input=stdin, capture_output=True, text=True,
                       timeout=60, env=full)
    for s in (PW, SECRET, "s3cr3ttoken42"):
        assert s not in p.stdout and s not in p.stderr
    return p


def rpc(calls: list[tuple[str, dict]], env: dict) -> list[dict]:
    msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"}]
    msgs += [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls, 1)]
    p = run([], env, "".join(json.dumps(m) + "\n" for m in msgs))
    out = [json.loads(x) for x in p.stdout.splitlines()]
    assert out[0]["result"]["serverInfo"]["name"] == "gas-pult-calendar" and len(out) == len(calls) + 1
    return out[1:]


def call(name: str, args: dict | None = None) -> tuple[str, dict]:
    return "tools/call", {"name": name, "arguments": args or {}}


def body(resp: dict):
    assert not resp["result"]["isError"], resp["result"]["content"][0]["text"]
    return json.loads(resp["result"]["content"][0]["text"])


def err(resp: dict) -> str:
    assert resp["result"]["isError"], resp["result"]["content"][0]["text"]
    return resp["result"]["content"][0]["text"]


WEEK = {"from": "2026-11-16", "to": "2026-11-22"}


# ---------- MCP и чтение ----------
def test_tools_list(env):
    (r,) = rpc([("tools/list", {})], env)
    names = [t["name"] for t in r["result"]["tools"]]
    assert names == ["calendar_list_calendars", "calendar_list_events", "calendar_get_event",
                     "calendar_propose_event", "calendar_apply"]
    assert all("fn" not in t and t["description"] for t in r["result"]["tools"])
    assert "Limited Use" in next(t for t in r["result"]["tools"] if t["name"] == "calendar_list_events")[
        "description"]


def test_list_calendars_discovery_hides_secrets(env):
    (r,) = rpc([call("calendar_list_calendars")], env)
    rows = {c["calendar"]: c for c in body(r)["calendars"]}
    assert rows["family"]["kind"] == "ics" and "нет" in rows["family"]["write"] and "url" not in rows["family"]
    y = rows["yandex"]
    # календарь задач (VTODO) и входящие — не календари событий
    assert y["user"] == USER and y["collections"] == [{"name": "Работа", "href": WORK}]
    assert [(s["m"], s["path"], s["depth"]) for s in DAV.seen] == [
        ("PROPFIND", "/", "0"), ("PROPFIND", "/principals/uk-dom/", "0"), ("PROPFIND", "/calendars/uk-dom/", "1")]
    assert not writes()


def test_caldav_week_timezones_allday_rrule(env):
    (r,) = rpc([call("calendar_list_events", {"calendar": "yandex", **WEEK})], env)
    d = body(r)
    assert d["period"] == {"from": "2026-11-16", "to": "2026-11-22", "tz": "Europe/Moscow"}
    got = [(e["start"], e["end"], e["summary"]) for e in d["events"]]
    assert got == [
        ("2026-11-16T10:00:00+03:00", "2026-11-16T10:15:00+03:00", "Планёрка"),
        ("2026-11-18T10:00:00+03:00", "2026-11-18T10:15:00+03:00", "Планёрка"),
        ("2026-11-19T10:00:00+03:00", "2026-11-19T11:00:00+03:00", "Стоматолог"),        # UTC 07:00 → МСК
        ("2026-11-20", "2026-11-21", "Отпуск"),                                          # DTEND даты — не включительно
        ("2026-11-20T10:00:00+03:00", "2026-11-20T10:15:00+03:00", "Планёрка")]
    plan = d["events"][0]
    assert plan["location"] == "Офис, переговорная 2" and plan["recurrence"].endswith("COUNT=10")
    assert plan["id"] == WORK + "standup.ics" and plan["collection"] == "Работа"
    assert d["events"][3]["all_day"] is True and d["total"] == 5
    (u,) = d["recurring_unexpanded"]                   # YEARLY с BYMONTH+BYDAY — честно не разворачиваем
    assert u["summary"] == "Собрание ТСЖ" and "BYDAY=3TH" in u["recurrence"] and "не поддерживается" in u["recurrence"]
    rep = next(s for s in DAV.seen if s["m"] == "REPORT")
    assert rep["path"] == WORK and rep["depth"] == "1"
    assert 'start="20261115T210000Z" end="20261122T210000Z"' in rep["body"] and not writes()


def test_rrule_exdate_and_moved_occurrence(env):
    (r,) = rpc([call("calendar_list_events", {"calendar": "yandex", "from": "2026-11-09", "to": "2026-11-15"})], env)
    got = [(e["start"], e["summary"]) for e in body(r)["events"]]
    # 11.11 — EXDATE, 13.11 — перенесён на 12:00 (RECURRENCE-ID)
    assert got == [("2026-11-09T10:00:00+03:00", "Планёрка"), ("2026-11-13T12:00:00+03:00", "Планёрка (перенесена)")]


def test_monthly_byday_and_count_end(env):
    (r,) = rpc([call("calendar_list_events", {"calendar": "yandex", "from": "2026-11-21", "to": "2027-01-10"})], env)
    got = [(e["start"], e["summary"]) for e in body(r)["events"] if not e.get("all_day")]
    # планёрка: 10-й повтор — 23.11, дальше нет; отчёт — первый понедельник месяца, 1 ч 30 мин
    assert got == [("2026-11-23T10:00:00+03:00", "Планёрка"), ("2026-12-07T09:00:00+03:00", "Отчёт за месяц"),
                   ("2027-01-04T09:00:00+03:00", "Отчёт за месяц")]
    assert body(r)["events"][-1]["end"] == "2027-01-04T10:30:00+03:00"


def test_ics_feed_floating_unknown_tz_daily_until_yearly(env):
    (r,) = rpc([call("calendar_list_events", {"calendar": "family", **WEEK, "tz": "Asia/Yekaterinburg"})], env)
    d = body(r)
    got = [(e["start"], e["summary"]) for e in d["events"]]
    assert got == [("2026-11-16T10:00:00+05:00", "Таблетки маме"),
                   ("2026-11-17", "День рождения"),
                   ("2026-11-17T10:00:00+05:00", "Таблетки маме"),
                   ("2026-11-17T12:00:00+05:00", "Непонятный пояс"),
                   ("2026-11-18T10:00:00+05:00", "Таблетки маме"),
                   ("2026-11-18T15:00:00+05:00", "Звонок внуку"),     # без пояса — время пояса ответа
                   ("2026-11-19T10:00:00+05:00", "Таблетки маме")]    # UNTIL 19.11 — дальше нет; отменённой нет
    mars = next(e for e in d["events"] if e["summary"] == "Непонятный пояс")
    assert "Mars/Olympus" in mars["note"] and mars["id"] == "mars-0103@google.com"
    (g,) = [s for s in DAV.seen if s["path"] == "<secret>"]
    assert g["auth"] is None                           # ссылке iCal пароль не нужен и не отправляется


def test_all_calendars_default_period(env):
    (r,) = rpc([call("calendar_list_events")], env)
    d = body(r)
    today = datetime.now(MSK).date()
    assert d["period"]["from"] == today.isoformat() and (datetime.fromisoformat(d["period"]["to"]).date()
                                                         - today).days == 6
    assert {e["calendar"] for e in d["events"]} <= {"yandex", "family"}


def test_get_event_caldav_and_ics(env):
    r1, r2, r3, r4 = rpc([call("calendar_get_event", {"calendar": "yandex", "id": WORK + "dentist.ics"}),
                          call("calendar_get_event", {"calendar": "yandex", "id": WORK + "standup.ics"}),
                          call("calendar_get_event", {"calendar": "family", "id": "pills-0101@google.com"}),
                          call("calendar_get_event", {"calendar": "yandex", "id": "/etc/passwd"})], env)
    a = body(r1)
    assert a["summary"] == "Стоматолог" and a["start"] == "2026-11-19T10:00:00+03:00"
    assert a["description"] == ("Клиника на Ленина, 5.\nВзять полис; приехать за 10 минут. Это длинная строка, "
                                "перенесённая по RFC 5545.")
    assert a["organizer"] == "clinic@example.org" and a["attendees"] == ["patient@example.org"]
    b = body(r2)
    assert b["start"] == "2026-11-02T10:00:00+03:00" and "WEEKLY" in b["recurrence"]
    c = body(r3)
    assert c["summary"] == "Таблетки маме" and c["start"] == "2026-11-16T08:00:00+03:00"
    assert "не из календарей" in err(r4) and not writes()


def test_bad_period_and_names(env):
    r1, r2, r3, r4, r5 = rpc([call("calendar_list_events", {"from": "завтра"}),
                              call("calendar_list_events", {"from": "2026-01-01", "to": "2027-06-01"}),
                              call("calendar_list_events", {"calendar": "../etc"}),
                              call("calendar_list_events", {"calendar": "yandex", "collection": "Нет такого"}),
                              call("calendar_get_event", {"id": "x"})], env)
    assert "ГГГГ-ММ-ДД" in err(r1) and "не больше 366" in err(r2) and "неверное имя" in err(r3)
    assert "нет календаря «Нет такого»" in err(r4) and "укажите calendar: family, yandex" in err(r5)


def test_password_never_leaks(env):
    DAV.mode = "badauth"                               # сервер повторяет пароль в тексте ошибки
    r1, r2 = rpc([call("calendar_list_events", {"calendar": "yandex"}), ("ping", {})], env)
    text = err(r1)
    assert "401" in text and "вход не удался" in text and "***" in text and r2["result"] == {}


def test_no_key_file_and_plain_http(env, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r1, r2 = rpc([call("calendar_list_events"), call("calendar_list_calendars")], env | {"GAS_CAL_KEY_DIR": str(empty)})
    assert "нет файла календаря calendar-<имя>.json" in err(r1) and "нет файла календаря" in err(r2)
    (Path(env["GAS_CAL_KEY_DIR"]) / "calendar-remote.json").write_text(json.dumps(
        {"kind": "ics", "url": "http://calendar.example.org/basic.ics"}))
    (r,) = rpc([call("calendar_list_events", {"calendar": "remote"})], env)
    assert "только для проверки на 127.0.0.1" in err(r)


# ---------- Google API Limited Use ----------
def test_google_limited_use(env):
    keys = Path(env["GAS_CAL_KEY_DIR"])
    (keys / "calendar-family.json").write_text(json.dumps({"kind": "ics", "url": env["_base"] + SECRET,
                                                           "google": True}))
    for model in ("deepseek/deepseek-chat", "meta-llama/llama-3.3-70b-instruct:free", "nvidia/nemotron-trial"):
        r1, r2, r3 = rpc([call("calendar_list_events", {"calendar": "family", **WEEK}),
                          call("calendar_get_event", {"calendar": "family", "id": "pills-0101@google.com"}),
                          call("calendar_list_events", WEEK)], env | {"OPENROUTER_MODEL": model})
        assert "данные Google нельзя этой модели (Limited Use)" in err(r1) and "Limited Use" in err(r2)
        d = body(r3)                                   # все календари: Google пропущен, Яндекс — показан
        assert d["skipped"][0]["calendar"] == "family" and {e["calendar"] for e in d["events"]} == {"yandex"}
    assert not [s for s in DAV.seen if s["path"] == "<secret>"]      # данные Google даже не скачивались
    # пульт проверил поставщика окна — можно; :free — никогда
    (r,) = rpc([call("calendar_list_events", {"calendar": "family", **WEEK})],
               env | {"GAS_PULT_MODEL": "deepseek/deepseek-chat", "GAS_CAL_GOOGLE_OK": "1"})
    assert body(r)["total"] == 7
    (r,) = rpc([call("calendar_list_events", {"calendar": "family", **WEEK})],
               env | {"OPENROUTER_MODEL": "x/y:free", "GAS_CAL_GOOGLE_OK": "1"})
    assert "Limited Use" in err(r)
    (r,) = rpc([call("calendar_list_events", {"calendar": "family", **WEEK})], env | {"ANTHROPIC_MODEL": "claude-x"})
    assert body(r)["total"] == 7


def test_google_host_detected(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_CAL_KEY_DIR", str(tmp_path))
    (tmp_path / "calendar-g.json").write_text(json.dumps(
        {"kind": "ics", "url": "https://calendar.google.com/calendar/ical/x%40example.org/private-abc/basic.ics"}))
    assert cal._cal("g")[1]["google"] is True
    monkeypatch.setenv("GAS_PULT_MODEL", "deepseek-chat")
    monkeypatch.delenv("GAS_CAL_GOOGLE_OK", raising=False)
    assert "Limited Use" in cal.google_block_reason()
    assert "private-abc" in " ".join(cal._secrets())   # секретная ссылка — в списке того, что прячем


# ---------- запись ----------
def _confirm(pid: str, env: dict):
    p = run(["confirm", pid], env)
    assert p.returncode == 0, p.stderr


def test_create_only_after_confirmation_then_one_put(env):
    (r,) = rpc([call("calendar_propose_event", {"calendar": "yandex", "summary": "Осмотр крыши, дом 7",
                                                "start": "2026-11-24T15:00", "duration_minutes": 90,
                                                "location": "ул. Ленина, 7", "description": "Взять ключ\nот чердака"})],
               env)
    d = body(r)
    assert "СОЗДАТЬ" in d["summary"] and "24.11.2026 15:00–16:30 (Europe/Moscow)" in d["summary"]
    assert d["params"]["start"] == "20261124T120000Z" and d["params"]["href"].startswith(WORK)
    assert not writes()
    pid = d["id"]
    r1, r2 = rpc([call("calendar_apply", {"id": pid}), call("calendar_apply", {"id": pid})],
                 env | {"GAS_CAL_WRITE": "1"})
    assert "нет подтверждения" in err(r1) and "нет подтверждения" in err(r2) and not writes()
    _confirm(pid, env)
    (r,) = rpc([call("calendar_apply", {"id": pid})], env)
    assert "запись выключена" in err(r) and not writes()
    r1, r2 = rpc([call("calendar_apply", {"id": pid}), call("calendar_apply", {"id": pid})],
                 env | {"GAS_CAL_WRITE": "1"})
    assert body(r1)["uid"] == d["params"]["uid"] and "не найден" in err(r2)
    (w,) = writes()
    assert w["path"] == d["params"]["href"] and w["inm"] == "*"   # существующее не перезаписать
    (ev,) = cal.parse_ics(w["body"])
    assert ev["SUMMARY"][0][1] == "Осмотр крыши\\, дом 7" and ev["DTEND"][0][1] == "20261124T133000Z"
    assert ev["DESCRIPTION"][0][1] == "Взять ключ\\nот чердака"
    assert all(len(x.encode()) <= 75 for x in w["body"].split("\r\n"))
    # новое событие читается обратно
    (r,) = rpc([call("calendar_list_events", {"calendar": "yandex", "from": "2026-11-24", "to": "2026-11-24"})], env)
    assert [e["summary"] for e in body(r)["events"]] == ["Осмотр крыши, дом 7"]


def test_create_all_day_and_validation(env):
    r1, r2, r3, r4, r5 = rpc([
        call("calendar_propose_event", {"calendar": "yandex", "summary": "Субботник", "start": "2026-11-28",
                                        "end": "2026-11-29"}),
        call("calendar_propose_event", {"calendar": "family", "summary": "т", "start": "2026-11-28"}),
        call("calendar_propose_event", {"calendar": "yandex", "summary": " ", "start": "2026-11-28"}),
        call("calendar_propose_event", {"calendar": "yandex", "summary": "т", "start": "в обед"}),
        call("calendar_propose_event", {"calendar": "yandex", "summary": "т", "start": "2026-11-28T10:00",
                                        "end": "2026-11-28T09:00"})], env)
    d = body(r1)
    assert "28.11.2026–29.11.2026, весь день" in d["summary"]
    assert "только чтение" in err(r2) and "summary" in err(r3) and "ГГГГ-ММ-ДД" in err(r4) and "раньше" in err(r5)
    _confirm(d["id"], env)
    (r,) = rpc([call("calendar_apply", {"id": d["id"]})], env | {"GAS_CAL_WRITE": "1"})
    body(r)
    (ev,) = cal.parse_ics(writes()[0]["body"])
    assert ev["DTSTART"][0] == ({"VALUE": "DATE"}, "20261128") and ev["DTEND"][0][1] == "20261130"


# ---------- разбор iCalendar без сервера ----------
def test_dst_weekly_keeps_wall_clock():
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x\r\nDTSTART;TZID=Europe/Berlin:20261019T100000\r\n"
           "DURATION:PT1H\r\nRRULE:FREQ=WEEKLY;COUNT=3\r\nSUMMARY:Встреча\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    tz = ZoneInfo("Europe/Berlin")
    evs = cal.events_in(cal.parse_ics(ics), datetime(2026, 10, 1, tzinfo=tz), datetime(2026, 12, 1, tzinfo=tz), tz)
    # 25.10 — переход на зимнее время: 10:00 остаётся 10:00, смещение меняется
    assert [e["start"] for e in evs] == ["2026-10-19T10:00:00+02:00", "2026-10-26T10:00:00+01:00",
                                         "2026-11-02T10:00:00+01:00"]


def test_monthly_31st_and_last_friday_and_windows_tz():
    ics = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:a\nDTSTART:20260131T090000Z\nRRULE:FREQ=MONTHLY;COUNT=4\n"
           "SUMMARY:a\nEND:VEVENT\nBEGIN:VEVENT\nUID:b\nDTSTART;TZID=Russian Standard Time:20260130T180000\n"
           "RRULE:FREQ=MONTHLY;BYDAY=-1FR;UNTIL=20260430T000000Z\nSUMMARY:b\nEND:VEVENT\nEND:VCALENDAR\n")
    tz = ZoneInfo("UTC")
    evs = cal.events_in(cal.parse_ics(ics), datetime(2026, 1, 1, tzinfo=tz), datetime(2027, 1, 1, tzinfo=tz), tz)
    a = [e["start"][:10] for e in evs if e["summary"] == "a"]
    b = [e["start"] for e in evs if e["summary"] == "b"]
    assert a == ["2026-01-31", "2026-03-31", "2026-05-31", "2026-07-31"]   # месяцы без 31-го пропускаются
    assert b == ["2026-01-30T15:00:00+00:00", "2026-02-27T15:00:00+00:00", "2026-03-27T15:00:00+00:00",
                 "2026-04-24T15:00:00+00:00"]


def test_icloud_partition_host_is_same_site():
    """iCloud: вход на caldav.icloud.com, календари — на узле pNN-caldav.icloud.com (calendar-home-set)."""
    root = "https://caldav.icloud.com/"
    assert cal._same_site("https://p52-caldav.icloud.com:443/123/calendars/", root)
    assert cal._same_site("https://caldav.icloud.com:443/x", root)          # порт по умолчанию — тот же сервер
    assert not cal._same_site("http://p52-caldav.icloud.com/123/", root)    # без шифрования — нет
    assert not cal._same_site("https://p52-caldav.icloud.com:8443/123/", root)
    assert not cal._same_site("https://bad-icloud.com/123/", root)          # чужой домен с похожим именем
    assert not cal._same_site("https://icloud.com.bad.example/123/", root)
    assert not cal._same_site("https://caldav.yandex.ru/x", root)
    assert not cal._same_site("https://other.yandex.ru/x", "https://caldav.yandex.ru/")   # только _SITES


def test_apply_writes_to_collection_host(env):
    """Событие пишется на узел календаря (url из черновика), а не на адрес входа; путь — тот, что показан."""
    (r,) = rpc([call("calendar_propose_event", {"calendar": "yandex", "summary": "Узел",
                                                "start": "2026-11-25T10:00"})], env)
    d = body(r)
    assert d["params"]["url"].endswith(d["params"]["href"])
    _confirm(d["id"], env)
    (r,) = rpc([call("calendar_apply", {"id": d["id"]})], env | {"GAS_CAL_WRITE": "1"})
    assert body(r)["uid"] == d["params"]["uid"] and writes()[-1]["path"] == d["params"]["href"]
