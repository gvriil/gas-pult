"""Таблицы маршрутов (MONOLITH-PLAN §3.2, шаг 7): пути области отвечают так же, как ветки старой цепочки.

``SNAP`` — снимок ответов (код, тип, тело) и вызовов ``Panel`` по каждому пути области «голос», снятый на коде до
переноса (ветки в ``webapp.H.get``/``post``). Перенос — только перенос: снимок не меняется.
Ещё: путь не объявлен в двух местах (таблица и цепочка), таблицы видны описи API, права — до таблиц.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import api_spec, routes, webapp, webauth
from gas_pult.config import Config

OWNER, VIEWER = 1, 2


@pytest.fixture
def srv(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    p = webapp.Panel(Config(token="1:T", owners=[OWNER]))
    p.people.add(VIEWER, "viewer", "Наблюдатель")
    for uid in (OWNER, VIEWER):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    log: list = []

    def rec(name, out):
        def f(*a, **kw):
            log.append([name, [x if isinstance(x, (str, int, bool, type(None))) else type(x).__name__ for x in a],
                        sorted(kw.items())])
            return out
        return f

    fakes = {"tts_text": b"MP3-about", "about_text": "о пульте", "stt_job_get": {"state": "done", "text": "т"},
             "voice_cards": {"cards": []}, "voice_preview": b"MP3-preview", "tts": b"MP3-tts",
             "tts_warm": {"warm": True}, "stt_job": {"id": "j1"}, "stt": "привет", "fallback_note": "",
             "rec_finish": {"id": "j2"}, "stt_retry": {"id": "j3"}, "choose_voice": None}
    for name, out in fakes.items():
        monkeypatch.setattr(p, name, rec(name, out))
    monkeypatch.setattr(p.recparts, "status", rec("recparts.status", {"segs": 0}))
    monkeypatch.setattr(p.recparts, "add", rec("recparts.add", {"ok": True}))
    monkeypatch.setattr(p.recparts, "drop", rec("recparts.drop", True))
    monkeypatch.setattr(p, "window", lambda wid: {"id": "@1", "path": "/tmp"} if wid == "@1" else None)
    monkeypatch.setattr(p.tmux, "window", lambda wid: None)
    s = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield {"base": f"http://127.0.0.1:{s.server_address[1]}", "tok": p.auth.issue(OWNER), "log": log,
           "viewer": p.auth.issue(VIEWER)}
    s.shutdown()


def call(srv, path, body: bytes | None = None, ctype="", tok=None):
    hdr = {"Cookie": f"{webauth.COOKIE}={tok or srv['tok']}", **({"Content-Type": ctype} if ctype else {})}
    try:
        r = urllib.request.urlopen(urllib.request.Request(srv["base"] + path, body, hdr))
    except urllib.error.HTTPError as e:
        r = e
    raw = r.read()
    ct = r.headers.get("Content-Type", "").split(";")[0]
    out = json.loads(raw) if ct == "application/json" else raw.decode()
    calls = list(srv["log"])
    srv["log"].clear()
    return [r.status if hasattr(r, "status") else r.code, ct, out, calls]


J = json.dumps
CASES = [    # (путь с запросом, тело или None для GET, Content-Type)
    ("/api/tts/about?screen=home", None, ""),
    ("/api/rec/status?id=r1", None, ""),
    ("/api/stt/job?id=j1", None, ""),
    ("/api/voice/cards", None, ""),
    ("/api/voice/preview?id=v1", None, ""),
    ("/api/tts?w=%401&msg=3&full=1&head=1", None, ""),
    ("/api/tts?w=%409", None, ""),                     # окна нет — 404, как в цепочке после w = self.win(…)
    ("/api/tts/warm?w=%401", None, ""),
    ("/api/tts/warm", None, ""),                       # без окна — тоже 404 (ветка шла после w = self.win(…))
    ("/api/rec/chunk?id=r1&seg=0&seq=2", b"AUDIO", "audio/webm"),
    ("/api/rec/chunk?id=r1&seg=x", b"AUDIO", "audio/webm"),
    ("/api/stt", b"AUDIO", "audio/webm"),
    ("/api/stt?job=1", b"AUDIO", "audio/webm"),
    ("/api/rec/finish", J({"id": "r1"}).encode(), "application/json"),
    ("/api/rec/finish", b"{bad", "application/json"),
    ("/api/rec/drop", J({"id": "r1"}).encode(), "application/json"),
    ("/api/stt/retry", J({"id": "j1"}).encode(), "application/json"),
    ("/api/voice/choose", J({"id": "v2"}).encode(), "application/json"),
]

# Снимок — код до переноса (origin/refactor/panel-focus, eca3a81): [код, тип, тело, вызовы Panel].
SNAP = Path(__file__).with_name("fixtures") / "routes_voice_snap.json"


def test_voice_routes_answer_as_before(srv):
    got = {f"{i:02} {'GET' if b is None else 'POST'} {p}": call(srv, p, b, ct) for i, (p, b, ct) in enumerate(CASES)}
    assert json.loads(json.dumps(got)) == json.loads(SNAP.read_text(encoding="utf-8"))


def test_route_paths_not_in_old_chain():
    """Путь объявлен в одном месте: перенесённый в таблицу — не остался веткой в цепочке ``webapp.py``."""
    chain = api_spec.scan(api_spec.SRC.read_text(encoding="utf-8"))   # только webapp.py, без routes/
    both = [(m, p) for m, t in routes.TABLES.items() for p in t
            if ("GET" if m.startswith("GET") else "POST") in chain.get(p, {}).get("methods", ())]
    assert both == []


def test_tables_disjoint_and_named():
    seen: dict = {}
    for m, t in routes.TABLES.items():
        for p, fn in t.items():
            k = ("GET" if m.startswith("GET") else "POST", p)
            assert k not in seen, f"{k} — и в {seen[k]}, и в {m}"
            seen[k] = m
            assert p.startswith("/api/") and callable(fn)


def test_spec_sees_route_tables():
    spec = api_spec.scan()
    for m, t in routes.TABLES.items():
        for p in t:
            assert ("GET" if m.startswith("GET") else "POST") in spec[p]["methods"], p
    assert spec["/api/tts"]["in"][0] == "w"            # GET_W: окно сессии — как у веток после w = self.win(…)
    assert spec["/api/rec/finish"]["in"] == ["id"] and "Panel.rec_finish" in spec["/api/rec/finish"]["calls"]


def test_rights_checked_before_tables(srv):
    """Таблицы — после ``permit`` (одна точка прав): без входа — 401, наблюдателю запись — 403, владельческое — 403;
    до обработчика дело не доходит (вызовов ``Panel`` нет)."""
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(srv["base"] + "/api/voice/cards")
    assert e.value.code == 401 and srv["log"] == []
    v = srv["viewer"]
    assert call(srv, "/api/voice/choose", b'{"id": "v2"}', tok=v)[0::3] == [403, []]       # OWNER_ONLY
    assert call(srv, "/api/stt/retry", b'{"id": "j1"}', tok=v)[0::3] == [403, []]          # POST — участник и выше
    assert call(srv, "/api/stt", b"AUDIO", "audio/webm", tok=v)[0::3] == [403, []]
    assert call(srv, "/api/voice/cards", tok=v)[0] == 200                                   # смотреть — можно
