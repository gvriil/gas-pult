"""Сбои пульта — владельцу (alerts.py, docs/ALERTS.md): 500 JSON вместо обрыва, сводка ошибок не чаще раза в 30 минут
и без персональных данных, красный CI main — строка брифинга и одно сообщение, отметки жизни."""

import json
import subprocess
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from gas_pult import alerts, bot, brief, chatlog, webapp
from gas_pult.config import Config


# ---------- панель: исключение в обработчике → 500 JSON и событие ----------
@pytest.fixture
def server(monkeypatch):
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield p, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def get(url, cookie=""):
    req = urllib.request.Request(url, headers={"Cookie": cookie} if cookie else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def boom(*a, **kw):
    raise subprocess.CalledProcessError(1, ["tmux", "new-session"])


def test_handler_exception_is_500_json_and_event(server, monkeypatch, capsys):
    p, _ = server
    h = webapp.handler(p)
    monkeypatch.setattr(h, "permit", lambda self, path, method: True)   # вход — не предмет теста
    monkeypatch.setattr(h, "space", lambda self: "")
    monkeypatch.setattr(h, "get", boom)          # dispatch → get падает (как ensure_session ночью 22.11)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        code, d = get(f"http://127.0.0.1:{srv.server_address[1]}/api/projects?secret=1")
    finally:
        srv.shutdown()
    assert code == 500 and d["error"] == "внутренняя ошибка" and d["code"] == "server_error" and len(d["id"]) == 8
    ev = p.events.since(0, {"server_error"})
    assert ev and ev[-1]["path"] == "/api/projects" and ev[-1]["exc"] == "CalledProcessError"
    assert ev[-1]["id"] == d["id"] and "secret" not in json.dumps(ev)
    assert "Traceback" in capsys.readouterr().err                       # трассировка — в журнал службы


def test_top_level_exception_outside_dispatch_is_500(server, monkeypatch):
    p, _ = server
    h = webapp.handler(p)
    monkeypatch.setattr(h, "do_GET", lambda self: boom())               # упало мимо dispatch
    srv = ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        code, d = get(f"http://127.0.0.1:{srv.server_address[1]}/whatever")
    finally:
        srv.shutdown()
    assert code == 500 and d["code"] == "server_error"
    assert p.events.since(0, {"server_error"})[-1]["path"] == "/whatever"


def test_ok_request_writes_web_heartbeat(server):
    p, base = server
    code, _ = get(base + "/manifest.webmanifest")
    assert code == 200
    assert (p.cfg.data / "heartbeat-web").read_text().split()[0].isdigit()


# ---------- отметки жизни ----------
def test_beat_not_more_than_once_a_minute(tmp_path):
    assert alerts.beat(tmp_path, "bot", 1000.0)
    first = (tmp_path / "heartbeat-bot").read_text()
    assert first.startswith("1000 ")
    assert not alerts.beat(tmp_path, "bot", 1059.0)                    # раньше минуты — не пишем
    assert (tmp_path / "heartbeat-bot").read_text() == first
    assert alerts.beat(tmp_path, "bot", 1060.0)
    assert (tmp_path / "heartbeat-bot").read_text().startswith("1060 ")


# ---------- сводка ошибок: не чаще раза в 30 минут, без ПД ----------
def pult(tmp_path, clock):
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = SimpleNamespace(data=tmp_path, owners=[1])
    p.events = chatlog.Log(tmp_path / "chat-events.jsonl", clock=lambda: clock[0])
    p.sent = []
    p.broadcast = lambda text, kind="error", **kw: p.sent.append((kind, text))
    return p


def test_error_summary_rate_limited_and_without_personal_data(tmp_path):
    clock = [10_000.0]
    p = pult(tmp_path, clock)
    p.fail_tick(clock[0])                                                # первый запуск — «отсюда», старое не шлём
    assert p.sent == [] and (tmp_path / "heartbeat-bot").exists()
    for _ in range(6):
        clock[0] += 10
        p.events.event("server_error", path="/api/projects", exc="CalledProcessError", id="ab12cd34")
    p.events.event("server_error", path="/api/chat/@12/file/Паспорт Иванова.pdf", exc="TypeError", id="x")
    p.events.event("js_error", "m1", kind="error", msg="Иван Петров +79990000000", at="chat.js:10", screen="chat")
    clock[0] += 300
    p.fail_tick(clock[0])
    texts = [t for _, t in p.sent]
    assert {k for k, _ in p.sent} == {"error"} and len(texts) == 2
    assert texts[0].startswith("⚠ Панель: ошибки сервера — 7 за ") and "/api/projects ×6" in texts[0]
    assert "CalledProcessError" in texts[0] and "/api/chat/* ×1" in texts[0]
    assert texts[1].startswith("⚠ Панель: ошибки JS в браузере — 1 за ") and "chat ×1" in texts[1]
    blob = " ".join(texts)
    for bad in ("Иван", "7999", "Паспорт", "chat.js", "@12"):
        assert bad not in blob
    clock[0] += 300                                                      # новые ошибки через 5 мин — ещё рано
    p.events.event("server_error", path="/api/projects", exc="CalledProcessError", id="y")
    p.fail_tick(clock[0])
    assert len(p.sent) == 2
    clock[0] += 1800                                                     # прошло 30 мин — одна сводка за всё
    p.fail_tick(clock[0])
    assert len(p.sent) == 3 and p.sent[-1][1].startswith("⚠ Панель: ошибки сервера — 1 за ")
    clock[0] += 3600                                                     # новых нет — молчим
    p.fail_tick(clock[0])
    assert len(p.sent) == 3


# ---------- красный CI main: строка брифинга и одно сообщение ----------
RUNS = [
    {"databaseId": 5, "status": "in_progress", "conclusion": "", "createdAt": "2026-11-22T06:30:00Z",
     "updatedAt": "2026-11-22T06:31:00Z", "url": "https://github.com/o/r/actions/runs/5"},
    {"databaseId": 4, "status": "completed", "conclusion": "failure", "createdAt": "2026-11-22T05:00:00Z",
     "updatedAt": "2026-11-22T05:20:00Z", "url": "https://github.com/o/r/actions/runs/4"},
    {"databaseId": 3, "status": "completed", "conclusion": "cancelled", "createdAt": "2026-11-21T20:00:00Z",
     "updatedAt": "2026-11-21T20:01:00Z", "url": "https://github.com/o/r/actions/runs/3"},
    {"databaseId": 2, "status": "completed", "conclusion": "failure", "createdAt": "2026-11-21T14:10:00Z",
     "updatedAt": "2026-11-21T14:30:00Z", "url": "https://github.com/o/r/actions/runs/2"},
    {"databaseId": 1, "status": "completed", "conclusion": "success", "createdAt": "2026-11-21T13:00:00Z",
     "updatedAt": "2026-11-21T14:05:00Z", "url": "https://github.com/o/r/actions/runs/1"},
]


@pytest.fixture
def fake_gh(monkeypatch, tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        assert cmd[0] == "gh" and kw["cwd"] == str(tmp_path / "repo")
        out = RUNS if cmd[1:3] == ["run", "list"] else \
            {"jobs": [{"name": "lint", "conclusion": "success"}, {"name": "pytest (macos-latest, 3.12)",
                                                                  "conclusion": "failure"}]}
        return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")
    monkeypatch.setattr(alerts, "RUN", run)
    monkeypatch.setattr(alerts, "REPO", tmp_path / "repo")
    return calls


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def test_main_ci_red_since_first_failure(fake_gh):
    m = alerts.main_ci(now=ts("2026-11-22T07:00:00Z"))
    assert m["red"] and m["since"] == ts("2026-11-21T14:30:00Z") and m["job"] == "pytest (macos-latest, 3.12)"
    assert m["url"].endswith("/runs/4")
    assert alerts.main_ci(now=ts("2026-11-22T07:01:00Z")) == m and len(fake_gh) == 2    # 5 минут — из памяти


def test_brief_has_red_main_line(fake_gh, monkeypatch):
    monkeypatch.setattr(brief, "merged", lambda owner, since: [])
    now = datetime.fromtimestamp(ts("2026-11-21T20:00:00Z"))
    b = brief.collect(SimpleNamespace(digest_github="me"), sel={"sources": ["github"]}, digest_items=[],
                      tasks_list=[], now=now)
    line = b["failed"][-1]
    assert line["text"].startswith("CI main красный с ") and line["text"].endswith(": pytest (macos-latest, 3.12)")
    assert line["source"]["url"].endswith("/runs/4")
    assert "CI main красный" in brief.telegram(b)


def test_red_main_one_message_after_hour_and_once_in_6h(fake_gh, tmp_path):
    p = pult(tmp_path, [0.0])
    since = ts("2026-11-21T14:30:00Z")
    p.ci_tick(since + 30 * 60)                                           # красный полчаса — молчим
    assert p.sent == []
    alerts._ci_cache.clear()
    p.ci_tick(since + 2 * 3600)
    assert len(p.sent) == 1 and p.sent[0][1].startswith("⚠ CI main красный с ")
    assert "pytest (macos-latest, 3.12)" in p.sent[0][1] and p.sent[0][1].endswith("/runs/4")
    for h in (3, 5, 7):                                                  # раз в 6 часов, не чаще
        alerts._ci_cache.clear()
        p.ci_tick(since + h * 3600)
    assert len(p.sent) == 1
    alerts._ci_cache.clear()
    p.ci_tick(since + 8.5 * 3600)
    assert len(p.sent) == 2


def test_green_main_no_line_no_message(monkeypatch, tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    monkeypatch.setattr(alerts, "REPO", tmp_path / "repo")
    monkeypatch.setattr(alerts, "RUN", lambda cmd, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps([RUNS[-1]]), stderr=""))
    m = alerts.main_ci()
    assert m == {"red": False, "url": RUNS[-1]["url"]}
    assert alerts.Watch(tmp_path).ci(m) == ""
