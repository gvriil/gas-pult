"""Таблицы маршрутов (MONOLITH-PLAN §3.2, шаг 7): пути области отвечают так же, как ветки старой цепочки.

``AREAS`` — по области: запросы и снимок ответов (код, тип, тело) и вызовов ``Panel`` и модулей (``billing.api``,
``messengers.panel``) по каждому её пути, снятый на коде до переноса (ветки в ``webapp.H.get``/``post``): успех,
ошибка (404/400), битый JSON для POST, наблюдатель (403 до таблиц или свой ответ), через ``/api/v1`` — где путь в
белом списке ``V1_*`` (и 403 для ``V1_NEVER``). Перенос — только перенос: снимок не меняется.
Ещё: путь не объявлен в двух местах (таблица и цепочка), таблицы видны описи API, права — до таблиц.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import api_spec, onboarding, routes, webapp, webauth
from gas_pult.billing import api as billing_api
from gas_pult.config import Config
from gas_pult.messengers import panel as messengers_panel

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
            return out(*a, **kw) if callable(out) else out
        return f

    def miss(*a, **kw):                          # «нет такого» — LookupError (404), неверное — ValueError (400)
        flat = [x for v in a + tuple(kw.values()) for x in (v.values() if isinstance(v, dict) else [v])]
        if "nope" in flat:
            raise LookupError("нет такого")
        if "bad" in flat:
            raise ValueError("неверный ввод")

    def ok(val):
        return lambda *a, **kw: miss(*a, **kw) or val

    def area(*a, **kw):                          # billing.api и messengers.panel: путь и поля — в ответ
        flat = [x for v in a + tuple(kw.values()) for x in (v.values() if isinstance(v, dict) else [v])]
        miss(*flat)
        return {"ok": True, "path": next((x for x in a if isinstance(x, str) and x.startswith("/api/")), "")}

    fakes = {"tts_text": b"MP3-about", "about_text": "о пульте", "stt_job_get": {"state": "done", "text": "т"},
             "voice_cards": {"cards": []}, "voice_preview": b"MP3-preview", "tts": b"MP3-tts",
             "tts_warm": {"warm": True}, "stt_job": {"id": "j1"}, "stt": "привет", "fallback_note": "",
             "rec_finish": {"id": "j2"}, "stt_retry": {"id": "j3"}, "choose_voice": None,
             "meeting_list": {"meetings": []}, "meeting_view": ok({"id": "m1", "title": "Встреча"}),
             "meeting_audio": ok(("audio/webm", b"AUD", {"Cache-Control": "private, max-age=3600"})),
             "meeting_card": ok(("image/svg+xml; charset=utf-8", b"<svg/>", {"Cache-Control": "no-store"})),
             "meeting_share": ok({"url": "https://x/#focus=t", "id": "f1"}),
             "brief_get": {"cards": []}, "task_list": [{"id": "t1"}], "brief_set": ok({"ok": True}),
             "brief_act": ok({"ok": True}), "task_run": ok({"ok": True, "out": "готово"}),
             "share_list": {"items": []}, "share_file": ok(("image/jpeg", b"JPG")),
             "notify_info": {"channels": []}, "notify_set": ok({"ok": True}),
             "anketa_answers": ok({"answers": []})}
    for name, out in fakes.items():
        monkeypatch.setattr(p, name, rec(name, out))
    subs = {"tasks": {"etag": "E1", "add": ok({"id": "t2"}), "update": ok({"id": "t1"}), "remove": ok(True)},
            "share_tokens": {"mine": [{"id": "d1"}], "create": ok({"id": "d2", "token": "s"}), "revoke": ok(True)},
            "shares": {"done": ok({"ok": True})},
            "push": {"public_key": "PK", "devices": [{"id": "d1"}], "pending": [], "add": ok({"id": "d2"}),
                     "remove": ok(True), "notify": 1},
            "forms_links": {"listing": [{"id": "l1"}], "new": ok({"code": "c1"})},
            "api_tokens": {"mine": [{"id": "a1"}], "create": ok({"id": "a2", "token": "t"}), "revoke": ok(True)},
            "funnel": {"event": None}}
    for obj, names in subs.items():
        for name, out in names.items():
            monkeypatch.setattr(getattr(p, obj), name, rec(f"{obj}.{name}", out))
    monkeypatch.setattr(p.api_tokens, "check", lambda t: {"id": "a1", "by": OWNER, "space": "", "groups": ["tasks"],
                                                          "write": True} if t == "v1tok" else None)
    monkeypatch.setattr(onboarding, "forms", rec("onboarding.forms", {"f1": {"id": "f1", "title": "Анкета"}}))
    monkeypatch.setattr(p.recparts, "status", rec("recparts.status", {"segs": 0}))
    monkeypatch.setattr(p.recparts, "add", rec("recparts.add", {"ok": True}))
    monkeypatch.setattr(p.recparts, "drop", rec("recparts.drop", True))
    monkeypatch.setattr(billing_api, "get", rec("billing_api.get", area))
    monkeypatch.setattr(billing_api, "post", rec("billing_api.post", area))
    monkeypatch.setattr(messengers_panel, "get", rec("messengers_panel.get", {"services": []}))
    monkeypatch.setattr(messengers_panel, "post", rec("messengers_panel.post", area))
    monkeypatch.setattr(p.auth, "needs_confirm", lambda *a, **k: False)   # платежи: код подтверждения — не здесь
    monkeypatch.setattr(p, "window", lambda wid: {"id": "@1", "path": "/tmp"} if wid == "@1" else None)
    monkeypatch.setattr(p.tmux, "window", lambda wid: None)
    s = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield {"base": f"http://127.0.0.1:{s.server_address[1]}", "tok": p.auth.issue(OWNER), "log": log,
           "viewer": p.auth.issue(VIEWER)}
    s.shutdown()


# особые запросы владельца: свой заголовок (ETag, Host — адрес подписки не зависит от порта); "v1" — токен /api/v1
HDR = {"etag": {"If-None-Match": "E1"}, "host": {"Host": "pult.test"}}


def call(srv, path, body: bytes | None = None, ctype="", tok=None):
    extra = HDR.get(tok, {})
    tok = None if tok in HDR else srv.get(tok, tok)   # "viewer" — вход наблюдателя
    hdr = {"Cookie": f"{webauth.COOKIE}={tok or srv['tok']}", **({"Content-Type": ctype} if ctype else {}), **extra}
    if tok == "v1":                              # /api/v1/<путь>: токен 1С и CRM вместо куки
        path, hdr = "/api/v1/" + path.removeprefix("/api/"), {"Authorization": "Bearer v1tok",
                                                                **({"Content-Type": ctype} if ctype else {})}
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
VOICE = [    # (путь с запросом, тело или None для GET, Content-Type)
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

JS = "application/json"
MESSENGERS = [
    ("/api/messengers", None, ""),
    ("/api/messengers", None, "", "viewer"),            # только владельцу — 403 до таблиц
    *[x for w in ("consent", "off", "tg/login", "tg/code", "tg/password", "link", "chats", "allow")
      for x in ((f"/api/messengers/{w}", J({"svc": "signal", "accepted": True}).encode(), JS),
                (f"/api/messengers/{w}", J({"svc": "bad"}).encode(), JS),
                (f"/api/messengers/{w}", b"{bad", JS))],
    ("/api/messengers/nope", J({"svc": "signal"}).encode(), JS),   # не из таблицы прав — 403, до ветки не доходит
    ("/api/messengers/consent", J({"svc": "signal"}).encode(), JS, "viewer"),
]
BILLING = [
    ("/api/billing/plans", None, ""),
    ("/api/billing/invoices", None, ""),
    ("/api/billing/invoice?id=7", None, ""),
    ("/api/billing/invoice?id=nope", None, ""),
    ("/api/billing/invoice?id=bad", None, ""),
    ("/api/billing/plans", None, "", "viewer"),
    *[x for w in ("plan", "invoice/new", "invoice/issue", "invoice/pay", "invoice/void")
      for x in ((f"/api/billing/{w}", J({"key": "k1", "id": 7, "code": "pro"}).encode(), JS),
                (f"/api/billing/{w}", J({"key": "k2", "id": "nope"}).encode(), JS),
                (f"/api/billing/{w}", J({"key": "k3", "id": "bad"}).encode(), JS),
                (f"/api/billing/{w}", b"{bad", JS))],
    ("/api/billing/plan", J({"key": "k1"}).encode(), JS, "viewer"),
]
MEETINGS = [
    ("/api/meetings", None, ""),
    ("/api/meeting?id=m1", None, ""),
    ("/api/meeting?id=nope", None, ""),
    ("/api/meeting", None, ""),
    ("/api/meeting/audio?id=m1", None, ""),
    ("/api/meeting/audio?id=nope", None, ""),
    ("/api/meeting/card?id=m1", None, ""),
    ("/api/meeting/card?id=nope", None, ""),
    ("/api/meeting/share", J({"id": "m1", "base": "https://x"}).encode(), JS),
    ("/api/meeting/share", J({"id": "nope"}).encode(), JS),
    ("/api/meeting/share", J({"id": "m1", "base": "bad"}).encode(), JS),
    ("/api/meeting/share", b"{bad", JS),
    ("/api/meetings", None, "", "viewer"),
]

TASKS = [
    ("/api/brief", None, ""),
    ("/api/brief?fresh=1", None, ""),
    ("/api/tasks", None, ""),
    ("/api/tasks", None, "", "etag"),                   # не менялись — 304 без тела
    ("/api/tasks", None, "", "viewer"),                 # только владельцу — 403 до таблиц
    ("/api/tasks", None, "", "v1"),                     # /api/v1/tasks — токен с группой «tasks»
    ("/api/brief/prefs", J({"time": "08:00"}).encode(), JS),
    ("/api/brief/prefs", J({"time": "bad"}).encode(), JS),
    ("/api/brief/prefs", b"{bad", JS),
    ("/api/brief/act", J({"id": "b1", "act": "yes"}).encode(), JS),   # «Да» — событие воронки
    ("/api/brief/act", J({"id": "b1", "act": "later"}).encode(), JS),
    ("/api/brief/act", J({"id": "nope", "act": "no"}).encode(), JS),
    ("/api/brief/act", b"{bad", JS),
    ("/api/tasks/add", J({"title": "Позвонить"}).encode(), JS),
    ("/api/tasks/add", J({"title": "bad"}).encode(), JS),
    ("/api/tasks/add", b"{bad", JS),
    ("/api/tasks/add", J({"title": "Позвонить"}).encode(), JS, "viewer"),
    ("/api/tasks/add", J({"title": "Из CRM"}).encode(), JS, "v1"),
    ("/api/tasks/add", b"{bad", JS, "v1"),
    ("/api/tasks/update", J({"id": "t1", "status": "done"}).encode(), JS),
    ("/api/tasks/update", J({"id": "nope"}).encode(), JS),
    ("/api/tasks/update", b"{bad", JS),
    ("/api/tasks/update", J({"id": "t1", "status": "done"}).encode(), JS, "v1"),
    ("/api/tasks/remove", J({"id": "t1"}).encode(), JS),
    ("/api/tasks/remove", J({"id": "nope"}).encode(), JS),
    ("/api/tasks/remove", J({"id": "t1"}).encode(), JS, "v1"),   # V1_NEVER — 403
    ("/api/tasks/run", J({"id": "t1", "confirmed": True}).encode(), JS),
    ("/api/tasks/run", J({"id": "nope"}).encode(), JS),
    ("/api/tasks/run", b"{bad", JS),
]
SHARE = [
    ("/api/share/list", None, ""),
    ("/api/share/list", None, "", "viewer"),
    ("/api/share/file?id=s1&i=0", None, ""),
    ("/api/share/file?id=nope", None, ""),
    ("/api/share/devices", None, ""),
    ("/api/share/done", J({"id": "s1"}).encode(), JS),
    ("/api/share/done", J({"id": "nope"}).encode(), JS),
    ("/api/share/done", b"{bad", JS),
    ("/api/share/done", J({"id": "s1"}).encode(), JS, "viewer"),
    ("/api/share/devices/new", J({"name": "iPhone"}).encode(), JS),
    ("/api/share/devices/new", J({"name": "bad"}).encode(), JS),
    ("/api/share/devices/new", b"{bad", JS),
    ("/api/share/devices/revoke", J({"id": "d1"}).encode(), JS),
    ("/api/share/devices/revoke", J({"id": "nope"}).encode(), JS),
    ("/api/share/devices/revoke", b"{bad", JS),
]
NOTIFY = [
    ("/api/notify/prefs", None, ""),
    ("/api/push/key", None, ""),
    ("/api/push/devices", None, ""),
    ("/api/push/devices", None, "", "viewer"),          # свои подписки — и наблюдателю
    ("/api/push/last?dev=abc", None, ""),
    ("/api/push/last", None, ""),
    ("/api/notify/prefs", J({"events": ["done"]}).encode(), JS),
    ("/api/notify/prefs", J({"events": "bad"}).encode(), JS),
    ("/api/notify/prefs", b"{bad", JS),
    ("/api/push/subscribe", J({"sub": {"endpoint": "https://push/e"}, "label": "телефон"}).encode(), JS, "host"),
    ("/api/push/subscribe", J({"sub": {"endpoint": "bad"}}).encode(), JS, "host"),
    ("/api/push/subscribe", b"{bad", JS),
    ("/api/push/unsubscribe", J({"id": "d1"}).encode(), JS),
    ("/api/push/unsubscribe", J({"id": "nope"}).encode(), JS),
    ("/api/push/test", J({}).encode(), JS),
    ("/api/push/test", J({}).encode(), JS, "viewer"),
    ("/api/notify/prefs", J({"events": ["done"]}).encode(), JS, "v1"),   # V1_NEVER — 403
]
FORMS = [
    ("/api/q/list", None, ""),
    ("/api/q/list", None, "", "viewer"),
    ("/api/q/answers?id=a1", None, ""),
    ("/api/q/answers?id=nope", None, ""),
    ("/api/q/answers", None, ""),
    ("/api/q/new", J({"form": "f1", "client": "Иван", "days": 7}).encode(), JS),
    ("/api/q/new", J({"form": "f1"}).encode(), JS),
    ("/api/q/new", J({"form": "zz"}).encode(), JS),      # нет такой анкеты — 400
    ("/api/q/new", J({"form": "f1", "client": "bad"}).encode(), JS),
    ("/api/q/new", b"{bad", JS),
]
APITOKENS = [
    ("/api/apitokens", None, ""),
    ("/api/apitokens", None, "", "viewer"),             # наблюдателю токены не выдаются — 400
    ("/api/apitokens", None, "", "v1"),                 # V1_NEVER — 403
    ("/api/apitokens/new", J({"name": "1С", "write": True, "days": 30, "groups": ["tasks"]}).encode(), JS),
    ("/api/apitokens/new", J({"name": "CRM", "groups": "tasks"}).encode(), JS),
    ("/api/apitokens/new", J({"name": "bad"}).encode(), JS),
    ("/api/apitokens/new", b"{bad", JS),
    ("/api/apitokens/revoke", J({"id": "a1"}).encode(), JS),
    ("/api/apitokens/revoke", J({"id": "nope"}).encode(), JS),
    ("/api/apitokens/revoke", b"{bad", JS),
    ("/api/apitokens/revoke", J({"id": "a1"}).encode(), JS, "viewer"),
]

# Снимки — код до переноса: голос — origin/refactor/panel-focus (eca3a81), мессенджеры, платежи, протоколы встреч —
# main 5412efd; задачи и брифинг, «Поделиться», уведомления, анкеты, токены 1С и CRM — f6fdf33 (#456).
# [код, тип, тело, вызовы Panel и модулей].
FIX = Path(__file__).with_name("fixtures")
AREAS = {"voice": VOICE, "messengers": MESSENGERS, "billing": BILLING, "meetings": MEETINGS, "tasks": TASKS,
         "share": SHARE, "notify": NOTIFY, "forms": FORMS, "apitokens": APITOKENS}


def snap_of(srv, cases) -> dict:
    return {f"{i:02} {'GET' if c[1] is None else 'POST'} {c[0]}{' (' + c[3] + ')' if len(c) > 3 else ''}":
            call(srv, *c) for i, c in enumerate(cases)}


@pytest.mark.parametrize("area", AREAS)
def test_routes_answer_as_before(srv, area):
    got = json.loads(json.dumps(snap_of(srv, AREAS[area])))
    assert got == json.loads((FIX / f"routes_{area}_snap.json").read_text(encoding="utf-8"))


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
    assert spec["/api/billing/invoice"]["methods"] == ["GET"] and spec["/api/billing/plan"]["methods"] == ["POST"]
    assert spec["/api/meeting/share"]["in"] == ["base", "id"]


def test_fork_tables_keep_chain_paths():
    """``GET_P``/``POST_P`` — те же пути, что развилки цепочки: ``path in billing_api.GET``/``POST``,
    ``path.startswith("/api/messengers/") and path in OWNER_ONLY`` и ``path in ("/api/push/…", …)``."""
    push = set(webapp.PUSH_OWN) - {"/api/notify/prefs"}
    assert set(routes.notify.PUSH_GET) | set(routes.notify.PUSH_POST) == push
    assert set(routes.GET_P) == set(billing_api.GET) | set(routes.notify.PUSH_GET)
    assert set(routes.POST_P) == set(billing_api.POST) | {p for p in webapp.OWNER_ONLY
                                                          if p.startswith("/api/messengers/")} | set(
        routes.notify.PUSH_POST)
    assert all(routes.POST_P[p] is routes.messengers.messengers_post for p in routes.messengers.POST_PATHS)


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
