"""Таблицы маршрутов (MONOLITH-PLAN §3.2, шаг 7): пути области отвечают так же, как ветки старой цепочки.

``AREAS`` — по области: запросы и снимок ответов (код, тип, тело) и вызовов ``Panel`` и модулей (``billing.api``,
``messengers.panel``) по каждому её пути, снятый на коде до переноса (ветки в ``webapp.H.get``/``post``): успех,
ошибка (404/400), битый JSON для POST, наблюдатель (403 до таблиц или свой ответ), через ``/api/v1`` — где путь в
белом списке ``V1_*`` (и 403 для ``V1_NEVER``), по фокус-ссылке — где путь в ``FOCUS_*``. Ключи поставщиков —
только поддельные «test-key-…». Перенос — только перенос: снимок не меняется.
Ещё: путь не объявлен в двух местах (таблица и цепочка), таблицы видны описи API, права — до таблиц.
"""

import json
import os
import re
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import (
    api_spec,
    balance,
    calkeys,
    drafts,
    focus,
    funnel,
    models,
    onboarding,
    routes,
    selftest,
    spend,
    terms,
    webapp,
    webauth,
)
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
                        sorted((k, type(v).__name__ if callable(v) else v) for k, v in kw.items())])
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
             "anketa_answers": ok({"answers": []}),
             # модели, ключи, расход: ключи поставщиков — только поддельные «test-key-…», настоящие не читаются
             "setup_status": {"logged_in": True}, "openrouter_info": {"key": False}, "fallback_info": {"chain": []},
             "set_fallback": ok({"chain": ["a"]}), "cost_limits": {"day": 5}, "set_cost_limits": ok({"day": 7}),
             "voice_settings": {"keys": ["elevenlabs"], "tts": "el"}, "el_voices": [{"id": "e1"}],
             "set_key": ok({"ok": True, "provider": "openai"}), "remove_key": ok(None), "set_providers": ok(None),
             "login_check": ok({"state": "ok"}), "set_models": ok(None), "countries": ["NL"],
             # интеграции, репозитории, модули
             "modules_list": {"modules": []}, "mcp_login": ok({"url": "https://x/login"}),
             "module_create": ok({"w": "@6"}), "set_schedule": ok({"ok": True}), "module_delete": ok({"ok": True}),
             "repo_list": {"repos": []}, "repo_add": ok({"ok": True}), "repo_remove": ok({"ok": True}),
             "mcp_finish": ok("подключено")}
    for name, out in fakes.items():
        monkeypatch.setattr(p, name, rec(name, out))
    subs = {"tasks": {"etag": "E1", "add": ok({"id": "t2"}), "update": ok({"id": "t1"}), "remove": ok(True)},
            "share_tokens": {"mine": [{"id": "d1"}], "create": ok({"id": "d2", "token": "s"}), "revoke": ok(True)},
            "shares": {"done": ok({"ok": True})},
            "push": {"public_key": "PK", "devices": [{"id": "d1"}], "pending": [], "add": ok({"id": "d2"}),
                     "remove": ok(True), "notify": 1},
            "forms_links": {"listing": [{"id": "l1"}], "new": ok({"code": "c1"})},
            "api_tokens": {"mine": [{"id": "a1"}], "create": ok({"id": "a2", "token": "t"}), "revoke": ok(True)},
            "funnel": {"event": None, "read": [{"ev": "login"}]},
            "openrouter": {"models": [{"id": "m1"}], "start": "https://openrouter.test/auth"},
            "login": {"start": {"url": "https://claude.test/login"}, "send_code": ok({"ok": True}), "cancel": None},
            "mcp": {"list": [{"name": "gh"}], "connected": lambda m, h: {"ok": True, "state": "on"} if m == "Gmail"
                    else None, "add": ok("добавлено"), "remove": ok("удалено")},
            "approvals": {"grant": None}, "events": {"event": None},
            "pult": {"set_state": None, "cost_decide": ok("продолжено")}}
    for obj, names in subs.items():
        for name, out in names.items():
            monkeypatch.setattr(getattr(p, obj), name, rec(f"{obj}.{name}", out))
    monkeypatch.setattr(p.api_tokens, "check", lambda t: {"id": "a1", "by": OWNER, "space": "", "groups": ["tasks"],
                                                          "write": True} if t == "v1tok" else
                        {"id": "a3", "by": OWNER, "space": "", "groups": ["drafts"], "write": False}
                        if t == "v1dtok" else None)
    monkeypatch.setattr(onboarding, "forms", rec("onboarding.forms", {"f1": {"id": "f1", "title": "Анкета"}}))
    monkeypatch.setattr(p.tmux, "paste", rec("tmux.paste", None))
    mods = {selftest: {"public": {"state": "idle"}, "start": True}, spend: {"summary": ok({"usd": 1.5})},
            funnel: {"report": {"steps": []}}, balance: {"clear": {}}, models: {"public": [{"profile": "glm"}]},
            calkeys: {"status": [{"kind": "caldav", "ok": True}], "save": ok({"ok": True}), "remove": ok({"ok": True})},
            drafts: {"pending": [{"id": "d1"}], "digest": "H1", "reject": ok({"ok": True})}}
    for mod, names in mods.items():
        for name, out in names.items():
            monkeypatch.setattr(mod, name, rec(f"{mod.__name__.rsplit('.', 1)[1]}.{name}", out))
    for mod in (webapp, *routes.AREAS):              # каталог интеграций — короткий (где имя импортировано)
        if hasattr(mod, "PRESETS"):
            monkeypatch.setattr(mod, "PRESETS", [{"id": "github"}, {"id": "stdio"}])
            monkeypatch.setattr(mod, "CONNECTORS", [{"id": "gmail", "match": "Gmail"}])
            monkeypatch.setattr(mod, "CONNECTORS_URL", "https://connectors.test")
    rfoc = {"id": "f1", "w": "@5", "name": "Фокус", "space": None}       # фокус-ссылка на сессию @5
    monkeypatch.setattr(p, "focus_rec", lambda c: rfoc if c == "fc1" else (_ for _ in ()).throw(focus.Gone("нет")))
    monkeypatch.setattr(p.recparts, "status", rec("recparts.status", {"segs": 0}))
    monkeypatch.setattr(p.recparts, "add", rec("recparts.add", {"ok": True}))
    monkeypatch.setattr(p.recparts, "drop", rec("recparts.drop", True))
    monkeypatch.setattr(billing_api, "get", rec("billing_api.get", area))
    monkeypatch.setattr(billing_api, "post", rec("billing_api.post", area))
    monkeypatch.setattr(messengers_panel, "get", rec("messengers_panel.get", {"services": []}))
    monkeypatch.setattr(messengers_panel, "post", rec("messengers_panel.post", area))
    monkeypatch.setattr(p.auth, "needs_confirm", lambda *a, **k: False)   # платежи: код подтверждения — не здесь
    monkeypatch.setattr(p, "window", lambda wid: {"id": wid, "path": "/tmp"} if wid in ("@1", "@5") else None)
    monkeypatch.setattr(p.tmux, "window", lambda wid: {"id": "@5", "path": "/tmp/m"} if wid == "@5" else None)
    s = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield {"base": f"http://127.0.0.1:{s.server_address[1]}", "tok": p.auth.issue(OWNER), "log": log,
           "viewer": p.auth.issue(VIEWER), "p": p, "rec": rec, "ok": ok}
    s.shutdown()


# особые запросы владельца: свой заголовок (ETag, Host — адрес подписки не зависит от порта); "v1" — токен /api/v1
HDR = {"etag": {"If-None-Match": "E1"}, "host": {"Host": "pult.test"}, "origin": {"Origin": "https://evil.test"},
       "tgh": {"X-Telegram-Init-Data": "x"}}   # tgh: панель в Mini App (неверная подпись — вход по cookie владельца)
V1 = {"v1": "v1tok", "v1d": "v1dtok", "v1s": "v1stok"}   # токены с группой «tasks», «drafts» (чтение), «sessions»
FOC = {"focus": "fc1", "focusp": "fc2", "focusb": "fc3"}   # фокус-ссылка на сессию @5, на проект, с «Браузером»
ANON = {"anon": {}, "slink": {"Cookie": "gp_focus=sl1", "X-Gp-Slink": "1"},   # без входа; ссылка на пространство
        "slinkg": {"Cookie": "gp_focus=sl2", "X-Gp-Slink": "1"}}                  # погасшая ссылка на пространство


def call(srv, path, body: bytes | None = None, ctype="", tok=None):
    extra = HDR.get(tok, {})
    tok = None if tok in HDR else srv.get(tok, tok)   # "viewer" — вход наблюдателя
    hdr = {"Cookie": f"{webauth.COOKIE}={tok or srv['tok']}", **({"Content-Type": ctype} if ctype else {}), **extra}
    if tok in V1:                                # /api/v1/<путь>: токен 1С и CRM вместо куки
        path, hdr = "/api/v1/" + path.removeprefix("/api/"), {"Authorization": f"Bearer {V1[tok]}",
                                                                **({"Content-Type": ctype} if ctype else {})}
    if tok in FOC:                               # фокус-ссылка: только cookie фокуса
        hdr = {"Cookie": f"{focus.COOKIE}={FOC[tok]}", focus.HEADER: "1", **({"Content-Type": ctype} if ctype else {})}
    if tok in ANON:                              # без входа; ссылка на пространство — её cookie и заголовок страницы
        hdr = {**ANON[tok], **({"Content-Type": ctype} if ctype else {})}
    try:
        r = urllib.request.urlopen(urllib.request.Request(srv["base"] + path, body, hdr))
    except urllib.error.HTTPError as e:
        r = e
    raw = r.read()
    ct = r.headers.get("Content-Type", "").split(";")[0]
    out = json.loads(raw) if ct == "application/json" else raw.decode()
    calls = list(srv["log"])
    srv["log"].clear()
    got = [r.status if hasattr(r, "status") else r.code, ct, out, calls]
    if srv.get("cookies"):                       # люди и вход: и Set-Cookie — имя и атрибуты, значение скрыто
        got.append([_masked(c) for c in r.headers.get_all("Set-Cookie") or []])
    return got


def _masked(cookie: str) -> str:
    name, _, rest = cookie.partition("=")
    val, sep, attrs = rest.partition(";")
    return f"{name}={'*' if val else ''}{sep}{attrs}"


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

MODELS = [   # ключи — только поддельные «test-key-…»
    ("/api/setup/status", None, ""),
    ("/api/setup/status?fresh=1", None, ""),
    ("/api/setup/status", None, "", "viewer"),          # только владельцу — 403 до таблиц
    ("/api/openrouter/info", None, ""),
    ("/api/openrouter/models", None, ""),
    ("/api/fallback", None, ""),
    ("/api/selftest", None, ""),
    ("/api/cost/limits", None, ""),
    ("/api/spend?period=week", None, ""),
    ("/api/spend", None, ""),
    ("/api/spend?period=bad", None, ""),
    ("/api/providers", None, ""),
    ("/api/providers", None, "", "viewer"),
    ("/api/funnel", None, ""),
    ("/api/funnel?days=7&space=sp1", None, ""),
    ("/api/funnel?days=9999", None, ""),
    ("/api/funnel?space=..%2Fx", None, ""),            # неверное имя пространства — 400
    ("/api/funnel", None, "", "viewer"),
    ("/api/keys", J({"provider": "openai", "key": "test-key-abc"}).encode(), JS),
    ("/api/keys", J({"provider": "bad", "key": "test-key-x"}).encode(), JS),
    ("/api/keys", b"{bad", JS),
    ("/api/keys", J({"provider": "openai", "key": "test-key-v"}).encode(), JS, "viewer"),
    ("/api/keys", J({"provider": "openai", "key": "test-key-t"}).encode(), JS, "v1"),   # V1_NEVER — 403
    ("/api/keys/remove", J({"provider": "openai"}).encode(), JS),
    ("/api/keys/remove", J({"provider": "nope"}).encode(), JS),
    ("/api/providers", J({"tts": "el", "el_key": "test-key-el"}).encode(), JS),
    ("/api/providers", J({"tts": "bad"}).encode(), JS),
    ("/api/providers", b"{bad", JS),
    ("/api/setup/login", J({}).encode(), JS),
    ("/api/setup/code", J({"code": "123"}).encode(), JS),
    ("/api/setup/code", J({"code": "bad"}).encode(), JS),
    ("/api/login/code", J({"w": "@1", "code": " abc \n"}).encode(), JS),
    ("/api/login/code", J({"w": "@9", "code": "abc"}).encode(), JS),        # окна нет — 404
    ("/api/login/code", b"{bad", JS),
    ("/api/login/check", J({"w": "@1", "kind": "claude"}).encode(), JS),
    ("/api/login/check", J({"w": "@9"}).encode(), JS),
    ("/api/login/check", J({"w": "@1", "kind": "bad"}).encode(), JS),
    ("/api/setup/cancel", J({}).encode(), JS),
    ("/api/balance/clear", J({"profile": "glm"}).encode(), JS),
    ("/api/balance/clear", b"{bad", JS),
    ("/api/openrouter/start", J({}).encode(), JS, "host"),
    ("/api/fallback", J({"chain": ["a"]}).encode(), JS),
    ("/api/fallback", J({"chain": "bad"}).encode(), JS),
    ("/api/selftest", J({}).encode(), JS),
    ("/api/cost/limits", J({"day": 7}).encode(), JS),
    ("/api/cost/limits", J({"day": "bad"}).encode(), JS),
    ("/api/cost/decide", J({"w": "@1", "act": "go"}).encode(), JS),
    ("/api/cost/decide", J({"w": "@1", "act": "bad"}).encode(), JS),
    ("/api/models", J({"profile": "glm", "main": "m", "fast": "f", "base_url": "https://x"}).encode(), JS),
    ("/api/models", J({"profile": "glm", "main": "m"}).encode(), JS),
    ("/api/models", J({"profile": "bad"}).encode(), JS),
    ("/api/models", b"{bad", JS),
    ("/api/models", J({"profile": "glm"}).encode(), JS, "viewer"),
]
INTEGR = [
    ("/api/calendars/keys", None, ""),
    ("/api/calendars/keys", None, "", "viewer"),
    ("/api/mcp", None, ""),
    ("/api/mcp?fresh=1", None, ""),
    ("/api/mcp", None, "", "viewer"),                    # участник и выше
    ("/api/mcp", None, "", "focus"),                     # фокус-ссылка — список своей сессии
    ("/api/modules", None, ""),
    ("/api/mcp/connected?id=gmail", None, ""),
    ("/api/mcp/connected?id=nope", None, ""),
    ("/api/mcp/connected", None, ""),
    ("/api/mcp/connected?id=gmail", None, "", "focus"),
    ("/api/drafts", None, ""),
    ("/api/drafts", None, "", "viewer"),
    ("/api/drafts", None, "", "v1d"),                    # /api/v1/drafts — токен с группой «drafts»
    ("/api/drafts", None, "", "v1"),                     # без группы — 403
    ("/api/repos?w=%405", None, ""),
    ("/api/repos?w=%409", None, ""),
    ("/api/repos?w=%405", None, "", "focus"),
    ("/api/repos?w=%401", None, "", "focus"),            # не окно ссылки — 403
    ("/api/mcp/add", J({"preset": "github", "name": "gh", "values": {"token": "test-key-gh"}}).encode(), JS),
    ("/api/mcp/add", J({"preset": "stdio", "name": "my"}).encode(), JS),
    ("/api/mcp/add", J({"preset": "bad"}).encode(), JS),
    ("/api/mcp/add", b"{bad", JS),
    ("/api/mcp/add", J({"preset": "github"}).encode(), JS, "focus"),   # не из FOCUS_POST — 403
    ("/api/mcp/remove", J({"name": "gh"}).encode(), JS),
    ("/api/mcp/remove", J({"name": "nope"}).encode(), JS),
    ("/api/calendars/key", J({"kind": "caldav", "password": "test-key-cal"}).encode(), JS),
    ("/api/calendars/key", J({"kind": "bad"}).encode(), JS),
    ("/api/calendars/key", b"{bad", JS),
    ("/api/calendars/key", J({"kind": "caldav"}).encode(), JS, "viewer"),
    ("/api/calendars/key/remove", J({"kind": "caldav"}).encode(), JS),
    ("/api/calendars/key/remove", J({"kind": "nope"}).encode(), JS),
    ("/api/mcp/login", J({"name": "gh"}).encode(), JS),
    ("/api/mcp/login", J({"name": "nope"}).encode(), JS),
    ("/api/drafts/yes", J({"svc": "mail", "id": "d1"}).encode(), JS),
    ("/api/drafts/yes", J({"svc": "mail", "id": "d1"}).encode(), JS, "origin"),   # чужой сайт — 400
    ("/api/drafts/no", J({"svc": "mail", "id": "d1"}).encode(), JS),
    ("/api/drafts/no", J({"svc": "mail", "id": "nope"}).encode(), JS),
    ("/api/drafts/no", b"{bad", JS),
    ("/api/drafts/yes", J({"svc": "mail", "id": "d1"}).encode(), JS, "viewer"),
    ("/api/drafts/yes", J({"svc": "mail", "id": "d1"}).encode(), JS, "v1d"),     # V1_NEVER — 403
    ("/api/modules/create", J({"id": "m1", "name": "Модуль", "lang": "ru", "again": True}).encode(), JS),
    ("/api/modules/create", J({"id": "bad"}).encode(), JS),
    ("/api/modules/create", b"{bad", JS),
    ("/api/module/schedule", J({"w": "@5", "state": "pause"}).encode(), JS),
    ("/api/module/schedule", J({"w": "@9", "state": "pause"}).encode(), JS),
    ("/api/module/schedule", J({"w": "@5", "state": "bad"}).encode(), JS),
    ("/api/module/delete", J({"w": "@5", "confirm": "да"}).encode(), JS),
    ("/api/module/delete", J({"w": "@5", "confirm": "bad"}).encode(), JS),
    ("/api/module/delete", b"{bad", JS),
    ("/api/module/delete", J({"w": "@5"}).encode(), JS, "viewer"),
    ("/api/repos/add", J({"w": "@5", "repo": "o/r"}).encode(), JS),
    ("/api/repos/add", J({"w": "@9", "repo": "o/r"}).encode(), JS),
    ("/api/repos/add", J({"w": "@5", "repo": "bad"}).encode(), JS),
    ("/api/repos/add", J({"w": "@5", "repo": "o/r"}).encode(), JS, "focus"),
    ("/api/repos/remove", J({"w": "@5", "path": "/tmp/r"}).encode(), JS),
    ("/api/repos/remove", J({"w": "@5", "path": "nope"}).encode(), JS),
    ("/api/repos/remove", b"{bad", JS),
    ("/api/mcp/finish", J({"w": "@1", "url": "https://x/cb", "name": "gh"}).encode(), JS),
    ("/api/mcp/finish", J({"w": "@9", "url": "https://x/cb"}).encode(), JS),     # окна нет — 404
    ("/api/mcp/finish", J({"url": "https://x/cb"}).encode(), JS),                # без окна — тоже 404
    ("/api/mcp/finish", J({"w": "@1", "url": "bad"}).encode(), JS),
    ("/api/mcp/finish", b"{bad", JS),
    ("/api/mcp/finish", J({"w": "@5", "url": "https://x/cb", "name": "gh"}).encode(), JS, "focus"),
    ("/api/mcp/finish", J({"w": "@1", "url": "https://x/cb"}).encode(), JS, "focus"),   # не окно ссылки — 403
]

# Снимки — код до переноса: голос — origin/refactor/panel-focus (eca3a81), мессенджеры, платежи, протоколы встреч —
# main 5412efd; задачи и брифинг, «Поделиться», уведомления, анкеты, токены 1С и CRM — f6fdf33 (#456); модели, ключи,
# расход и интеграции, репозитории, модули — a187689 (#457; фокус-ссылка, /api/v1/drafts, POST_W /api/mcp/finish).
# [код, тип, тело, вызовы Panel и модулей].
FIX = Path(__file__).with_name("fixtures")
AREAS = {"voice": VOICE, "messengers": MESSENGERS, "billing": BILLING, "meetings": MEETINGS, "tasks": TASKS,
         "share": SHARE, "notify": NOTIFY, "forms": FORMS, "apitokens": APITOKENS, "models": MODELS,
         "integr": INTEGR}


def snap_of(srv, cases) -> dict:
    return {f"{i:02} {'GET' if c[1] is None else 'POST'} {c[0]}{' (' + c[3] + ')' if len(c) > 3 else ''}":
            call(srv, *c) for i, c in enumerate(cases)}


@pytest.mark.parametrize("area", AREAS)
def test_routes_answer_as_before(srv, area):
    got = json.loads(json.dumps(snap_of(srv, AREAS[area])))
    assert got == json.loads((FIX / f"routes_{area}_snap.json").read_text(encoding="utf-8"))


# своя ветка фокус-ссылки в ``H.focus_do`` (не цепочка): «Завершить» сессию пространства по ссылке — окно и
# пространство из записи ссылки, «Выйти» по ссылке — cookie фокуса; обычный запрос того же пути — таблица routes/
FOCUS_OWN = {("POST", "/api/space/close"), ("POST", "/api/logout")}
# своя ветка до входа в ``do_POST`` (не цепочка): помощник на экране входа без входа (``HELP_OPEN``, ``help_anon``);
# вошедшему — таблица routes/people.py
OPEN_OWN = {("POST", "/api/help/ask"), ("POST", "/api/help/feedback")}


def test_route_paths_not_in_old_chain():
    """Путь объявлен в одном месте: перенесённый в таблицу — не остался веткой в цепочке ``webapp.py``."""
    chain = api_spec.scan(api_spec.SRC.read_text(encoding="utf-8"))   # только webapp.py, без routes/
    both = [(m, p) for m, t in routes.TABLES.items() for p in t
            if ("GET" if m.startswith("GET") else "POST") in chain.get(p, {}).get("methods", ())]
    assert [x for x in both
            if (("GET" if x[0].startswith("GET") else "POST"), x[1]) not in FOCUS_OWN | OPEN_OWN] == []
    for m, p in OPEN_OWN:                                  # и до входа, и после — ветка до входа осталась на месте
        assert chain[p]["open"] == [m], p


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
    assert spec["/api/mcp/finish"]["in"] == ["w", "url", "name"]   # POST_W: окно — как после w = self.win(b…)
    assert spec["/api/chat/mcp"]["in"][0] == "w" and spec["/api/space/connect"]["in"] == ["w"]
    for p in ("/api/focus/bridge/pair", "/api/focus/bridge/revoke", "/api/focus/bridge/private"):   # focus_bridge —
        assert spec[p]["methods"] == ["POST"] and spec[p]["focus_only"], p        # в panel/focus.py, опись видит


def test_fork_tables_keep_chain_paths():
    """``GET_P``/``POST_P`` — те же пути, что развилки цепочки: ``path in billing_api.GET``/``POST``,
    ``path.startswith("/api/messengers/") and path in OWNER_ONLY`` и ``path in ("/api/push/…", …)``
    (черновики, модули, репозитории — ``path in ("/api/…", "/api/…")``)."""
    push = set(webapp.PUSH_OWN) - {"/api/notify/prefs"}
    assert set(routes.notify.PUSH_GET) | set(routes.notify.PUSH_POST) == push
    assert set(routes.GET_P) == set(billing_api.GET) | set(routes.notify.PUSH_GET) | {"/api/space/files",
                                                                                     "/api/space/download"}
    assert set(routes.POST_P) == set(billing_api.POST) | {p for p in webapp.OWNER_ONLY
                                                          if p.startswith("/api/messengers/")} | set(
        routes.notify.PUSH_POST) | {"/api/drafts/yes", "/api/drafts/no", "/api/module/schedule",
                                    "/api/module/delete", "/api/repos/add", "/api/repos/remove",
                                    "/api/space/mcp/add", "/api/space/mcp/remove", *webapp.CONFIRM_API,
                                    "/api/tty/type", "/api/tty/key", "/api/tty/size"}
    assert set(routes.POST_W) == {"/api/mcp/finish", "/api/chat/mcp", "/api/space/connect", "/api/help/call",
                                  "/api/run", "/api/run/term"}
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


# ---------------------------------------------------------------------- граница пространств: проекты, пространства,
# мост, фокус-ссылки. Человек пространства A (SPACER, «alpha») просит данные пространства B («beta», окно @8,
# проект «s:beta:…»): в снимке видно, куда ушёл запрос (вызовы Panel — с «alpha», не с «beta») или что он отклонён —
# до и после переноса.
SPACER = 3
FOC_RECS = {"fc1": {"id": "f1", "w": "@5", "name": "Фокус", "space": None},
            "fc2": {"id": "f2", "w": "", "proj": "pr1", "name": "Проект", "space": None},
            "fc3": {"id": "f3", "w": "@5", "name": "Браузер", "space": None, "browser": True}}


@pytest.fixture
def wide(srv, monkeypatch):
    """Подделки для областей «Проекты и чаты», «Пространства», «Мост», «Фокус-ссылки» и человек пространства A."""
    from gas_pult import bridge, ctxsnap, fallback, projects, qr, space_files, space_mcp, tenants
    p, rec, ok = srv["p"], srv["rec"], srv["ok"]
    p.people.add(SPACER, "member", "Тестировщик A", tenant="alpha")
    p.people.accept(SPACER)
    p.people.set_country(SPACER, chosen="NL")
    srv["spacer"] = p.auth.issue(SPACER)
    monkeypatch.setattr(p.cfg, "host", "pult-test")      # имя сервера — не машины, где идёт тест
    fakes = {"sessions": [{"id": "@1"}], "cost_summary": {"usd": 0}, "space_info": {"title": "Пространство A"},
             "projects_list": [{"id": "pr1"}], "space_projects_list": [{"id": "s:alpha:p1"}],
             "owner_space_projects": [], "project_data": {}, "check_budget": None,
             "project_info": ok({"id": "pr1"}), "space_project_info": ok({"id": "s:alpha:p1"}),
             "project_chats": ok({"chats": []}), "space_project_chats": ok({"chats": []}),
             "chat_trash_list": {"items": []}, "project_history": ok({"items": []}),
             "space_project_history": ok({"items": []}), "project_update": ok({"ok": True}),
             "project_chat": ok({"ok": True}), "chat_delete": ok({"ok": True}), "move_api": ok({"ok": True}),
             "chat_restore": ok({"ok": True}), "space_project_new": ok({"id": "s:alpha:new"}),
             "project_new": ok({"id": "pr9"}), "project_session": ok({"w": "@1"}),
             "project_resume": ok({"w": "@1"}), "space_project_session": ok({"w": "@7"}),
             "space_project_resume": ok({"w": "@7"}), "chat_mcp": ok({"ok": True}),
             "space_budget": {"usd": 5}, "space_list": ok({"sessions": []}), "budget_add": ok({"usd": 6}),
             "space_close": ok({"result": "closed"}), "space_resume": ok({"w": "@7"}),
             "space_delete": ok({"ok": True}), "space_restore": ok({"ok": True}), "space_task": ok({"ok": True}),
             "owner_join": ok({"ok": True}), "bridge_dev_ok": True,
             "focus_space": ok({"url": "https://x/#focus=t", "id": "f9"}),
             "focus_new": ok({"url": "https://x/#focus=t", "id": "f8"}), "focus_send": ok({"ok": True}),
             "focus_token": ok({"id": "f1"})}
    for name, out in fakes.items():
        monkeypatch.setattr(p, name, rec(name, out))
    subs = {"focus": {"listing": [{"id": "f1", "name": "Фокус"}], "set_browser": ok(True), "revoke": ok(True),
                      "end_window": None},
            "devices": {"listing": [{"id": "dv1", "name": "Мак", "focus": "f3"}, {"id": "dv2", "name": "ПК"}],
                        "pair_code": {"code": "123456"}, "revoke": ok(True), "set_private": ok(True)},
            "hub": {"online": ["dv1"], "history": ok([{"act": "click"}])},
            "approvals": {"grant": None, "pending": False}, "tasks": {"open_count": 2},
            "pult": {"module_root": "/tmp/mod"}}
    for obj, names in subs.items():
        for name, out in names.items():
            monkeypatch.setattr(getattr(p, obj), name, rec(f"{obj}.{name}", out))
    mods = {ctxsnap: {"limits": {"5h": 1}}, fallback: {"recent": []},
            projects: {"order_of": {"grp": []}, "tilde": "~/mod"},
            tenants: {"status": {"tenants": [{"slug": "alpha"}, {"slug": "beta"}]}},
            space_mcp: {"listing": [{"name": "gh"}], "presets": [{"id": "github"}], "add": ok({"ok": True}),
                        "remove": ok({"ok": True})},
            space_files: {"folder_of": "/tmp/sf", "listing": ok({"files": []}), "get": ok(("x.txt", b"DATA")),
                          "put": ok("x.txt")},
            bridge: {"drafts": [{"id": "bd1", "device": "dv1"}, {"id": "bd2", "device": "dvX"}],
                     "reject": ok(None)},
            bridge._core: {"_load": ok({"action": "click", "params": {}}), "_digest": "DG"},
            qr: {"png_of": b"PNG"}}
    for mod, names in mods.items():
        for name, out in names.items():
            monkeypatch.setattr(mod, name, rec(f"{mod.__name__.rsplit('.', 1)[1]}.{name}", out))
    wins = {"@5": {"id": "@5", "path": "/tmp/m"}, "@7": {"id": "@7", "path": "/tmp/a", "space": "alpha"},
            "@8": {"id": "@8", "path": "/tmp/b", "space": "beta"}}
    monkeypatch.setattr(p.tmux, "window", lambda wid: wins.get(wid))
    monkeypatch.setattr(p, "focus_rec", lambda c: FOC_RECS[c] if c in FOC_RECS else
                        (_ for _ in ()).throw(focus.Gone("нет")))
    monkeypatch.setattr(p, "focus_owns", lambda r, wid: (wid == r["w"]) if not r.get("proj") else wid == "@1")
    check = p.api_tokens.check
    monkeypatch.setattr(p.api_tokens, "check", lambda t: {"id": "a4", "by": OWNER, "space": "", "groups": ["sessions"],
                                                          "write": True} if t == "v1stok" else check(t))
    return srv


B_PROJ = "s:beta:secret"                            # проект пространства B
PROJECTS = [
    ("/api/projects", None, ""),
    ("/api/projects?q=x&archived=1", None, ""),
    ("/api/projects", None, "", "viewer"),
    ("/api/projects", None, "", "spacer"),               # человек A — проекты своего пространства
    ("/api/projects?archived=1", None, "", "spacer"),
    ("/api/projects", None, "", "v1s"),
    ("/api/projects", None, "", "focus"),                # не из FOCUS_* — 403
    ("/api/project?id=pr1", None, ""),
    ("/api/project?id=nope", None, ""),
    (f"/api/project?id={B_PROJ}", None, ""),              # владелец — проект пространства (любого)
    (f"/api/project?id={B_PROJ}", None, "", "viewer"),    # не владелец — «проекта нет»
    (f"/api/project?id={B_PROJ}", None, "", "spacer"),    # человек A — только в своё пространство («alpha»)
    ("/api/project?id=pr1", None, "", "spacer"),
    ("/api/project?id=pr1", None, "", "v1s"),
    ("/api/project?id=pr1", None, "", "focusp"),         # ссылка на проект pr1
    ("/api/project?id=pr2", None, "", "focusp"),         # чужой проект — 403
    ("/api/project/sessions?id=pr1&q=x&before=12.5", None, ""),
    ("/api/project/sessions?id=pr1&before=bad", None, ""),
    (f"/api/project/sessions?id={B_PROJ}", None, "", "spacer"),
    (f"/api/project/sessions?id={B_PROJ}", None, ""),
    ("/api/project/sessions?id=pr1", None, "", "v1s"),
    ("/api/project/sessions?id=pr1", None, "", "focusp"),
    ("/api/chat/trash", None, ""),
    ("/api/chat/trash", None, "", "viewer"),
    ("/api/chat/trash", None, "", "spacer"),
    ("/api/project/history?id=pr1&sid=s1&before=5", None, ""),
    ("/api/project/history?id=nope&sid=s1", None, ""),
    (f"/api/project/history?id={B_PROJ}&sid=s1", None, "", "spacer"),
    (f"/api/project/history?id={B_PROJ}&sid=s1", None, ""),
    ("/api/project/history?id=pr1&sid=s1", None, "", "v1s"),
    ("/api/project/history?id=pr2&sid=s1", None, "", "focusp"),
    ("/api/project/session", J({"id": "pr1", "profile": "claude", "model": "m", "mcp_off": ["gh"],
                                "effort": "high"}).encode(), JS),
    ("/api/project/session", J({"id": "nope"}).encode(), JS),
    ("/api/project/session", b"{bad", JS),
    ("/api/project/session", J({"id": B_PROJ, "effort": "low"}).encode(), JS),
    ("/api/project/session", J({"id": B_PROJ}).encode(), JS, "spacer"),
    ("/api/project/session", J({"id": "pr1"}).encode(), JS, "spacer"),
    ("/api/project/session", J({"id": B_PROJ}).encode(), JS, "viewer"),
    ("/api/project/session", J({"id": "pr1"}).encode(), JS, "focusp"),
    ("/api/project/session", J({"id": "pr2"}).encode(), JS, "focusp"),
    ("/api/project/resume", J({"id": "pr1", "sid": "s1"}).encode(), JS),
    ("/api/project/resume", J({"id": "nope", "sid": "s1"}).encode(), JS),
    ("/api/project/resume", b"{bad", JS),
    ("/api/project/resume", J({"id": B_PROJ, "sid": "s1"}).encode(), JS),
    ("/api/project/resume", J({"id": B_PROJ, "sid": "s1"}).encode(), JS, "spacer"),
    ("/api/project/resume", J({"id": "pr1", "sid": "s1"}).encode(), JS, "focusp"),
    ("/api/project/update", J({"id": "pr1", "name": "Новый", "archived": True}).encode(), JS),
    ("/api/project/update", J({"id": "nope"}).encode(), JS),
    ("/api/project/update", b"{bad", JS),
    ("/api/project/update", J({"id": B_PROJ}).encode(), JS, "spacer"),
    ("/api/project/chat", J({"id": "pr1", "sid": "s1", "title": "Т", "hidden": False}).encode(), JS),
    ("/api/project/chat", J({"id": "nope"}).encode(), JS),
    ("/api/project/chat", J({"id": "pr1"}).encode(), JS, "viewer"),
    ("/api/project/chat", J({"id": B_PROJ}).encode(), JS, "spacer"),
    ("/api/chat/delete", J({"w": "@1", "id": "pr1", "sid": "s1", "force": True}).encode(), JS),
    ("/api/chat/delete", J({"id": "nope"}).encode(), JS),
    ("/api/chat/delete", J({"w": "@8"}).encode(), JS, "spacer"),
    ("/api/chat/move", J({"sid": "s1", "to": "pr2"}).encode(), JS),
    ("/api/chat/move", J({"sid": "bad"}).encode(), JS),
    ("/api/chat/restore", J({"id": "c1"}).encode(), JS),
    ("/api/chat/restore", J({"id": "nope"}).encode(), JS),
    ("/api/chat/restore", b"{bad", JS),
    ("/api/project/new", J({"name": "Сайт", "folder": "site", "instructions": "И", "profile": "claude",
                            "model": "m"}).encode(), JS),
    ("/api/project/new", J({"name": "bad"}).encode(), JS),
    ("/api/project/new", b"{bad", JS),
    ("/api/project/new", J({"name": "Сайт", "instructions": "И", "folder": "/home/b"}).encode(), JS, "spacer"),
    ("/api/project/new", J({"name": "Сайт"}).encode(), JS, "viewer"),
    ("/api/chat/mcp", J({"w": "@1", "off": ["gh"]}).encode(), JS),
    ("/api/chat/mcp", J({"w": "@9", "off": []}).encode(), JS),          # окна нет — 404 (POST_W)
    ("/api/chat/mcp", J({"off": []}).encode(), JS),
    ("/api/chat/mcp", J({"w": "@1", "off": "bad"}).encode(), JS),
    ("/api/chat/mcp", b"{bad", JS),
    ("/api/chat/mcp", J({"w": "@8", "off": []}).encode(), JS, "spacer"),
    ("/api/chat/mcp", J({"w": "@1", "off": []}).encode(), JS, "viewer"),
]
SPACES = [
    ("/api/spaces", None, ""),
    ("/api/spaces", None, "", "viewer"),
    ("/api/spaces", None, "", "spacer"),
    ("/api/space/sessions?space=beta", None, ""),           # владелец — пространство из запроса
    ("/api/space/sessions?space=..", None, ""),
    ("/api/space/sessions", None, ""),                   # владельцу без space — 400
    ("/api/space/sessions?space=beta", None, "", "spacer"),  # человек A — только «alpha»
    ("/api/space/sessions", None, "", "viewer"),
    ("/api/space/mcp?space=beta", None, ""),
    ("/api/space/mcp?space=beta", None, "", "spacer"),
    ("/api/space/files?w=%407", None, "", "spacer"),
    ("/api/space/files?w=%408", None, "", "spacer"),     # окно пространства B — «окна уже нет»
    ("/api/space/files?w=%408", None, ""),               # владелец — окно любого пространства
    ("/api/space/files?w=%405", None, ""),               # не окно пространства — 404
    ("/api/space/files?w=%405", None, "", "focus"),
    ("/api/space/files?w=%401", None, "", "focus"),      # не окно ссылки — 403
    ("/api/space/download?w=%407&f=x.txt", None, "", "spacer"),
    ("/api/space/download?w=%408&f=x.txt", None, "", "spacer"),
    ("/api/space/download?w=%407&f=nope", None, "", "spacer"),
    ("/api/space/download?w=%408&f=x.txt", None, ""),
    ("/api/space/upload?w=%407", b"FILE", "application/octet-stream", "spacer"),
    ("/api/space/upload?w=%408", b"FILE", "application/octet-stream", "spacer"),
    ("/api/space/upload?w=%408", b"FILE", "application/octet-stream"),
    ("/api/space/upload?w=%407", b"FILE", "application/octet-stream", "viewer"),
    ("/api/space/upload?w=%405", b"FILE", "application/octet-stream", "focus"),
    ("/api/space/budget/add", J({"space": "beta", "usd": 5}).encode(), JS),
    ("/api/space/budget/add", J({"space": "..", "usd": 5}).encode(), JS),
    ("/api/space/budget/add", b"{bad", JS),
    ("/api/space/budget/add", J({"space": "beta", "usd": 5}).encode(), JS, "spacer"),
    ("/api/space/close", J({"space": "beta", "w": "@8", "force": True}).encode(), JS),
    ("/api/space/close", J({"space": "beta", "w": "nope"}).encode(), JS),
    ("/api/space/close", J({"w": "@8"}).encode(), JS),
    ("/api/space/close", b"{bad", JS),
    ("/api/space/close", J({"space": "beta", "w": "@8"}).encode(), JS, "spacer"),   # человек A — только «alpha»
    ("/api/space/close", J({"space": "beta", "w": "@8"}).encode(), JS, "viewer"),
    ("/api/space/close", J({"w": "@5"}).encode(), JS, "focus"),                  # фокус — focus_do, не цепочка
    ("/api/space/mcp/add", J({"preset": "github", "name": "gh", "values": {}}).encode(), JS),   # владелец — 400
    ("/api/space/mcp/add", J({"preset": "github", "name": "gh", "space": "beta"}).encode(), JS, "spacer"),
    ("/api/space/mcp/add", J({"preset": "bad"}).encode(), JS, "spacer"),
    ("/api/space/mcp/add", b"{bad", JS, "spacer"),
    ("/api/space/mcp/remove", J({"name": "gh", "space": "beta"}).encode(), JS, "spacer"),
    ("/api/space/mcp/remove", J({"name": "nope"}).encode(), JS, "spacer"),
    ("/api/space/mcp/remove", J({"name": "gh"}).encode(), JS, "viewer"),
    ("/api/space/resume", J({"space": "beta", "folder": "f1"}).encode(), JS),
    ("/api/space/resume", J({"space": "beta", "folder": "f1"}).encode(), JS, "spacer"),
    ("/api/space/resume", J({"folder": "nope"}).encode(), JS, "spacer"),
    ("/api/space/resume", J({"folder": "f1"}).encode(), JS),
    ("/api/space/delete", J({"space": "beta", "folder": "f1", "confirm": "да"}).encode(), JS),
    ("/api/space/delete", J({"space": "beta", "folder": "f1", "confirm": "да"}).encode(), JS, "spacer"),
    ("/api/space/delete", J({"folder": "f1", "confirm": "bad"}).encode(), JS, "spacer"),
    ("/api/space/delete", b"{bad", JS),
    ("/api/space/restore", J({"space": "beta", "id": "c1"}).encode(), JS),
    ("/api/space/restore", J({"space": "beta", "id": "c1"}).encode(), JS, "spacer"),
    ("/api/space/restore", J({"id": "nope"}).encode(), JS, "spacer"),
    ("/api/space/task", J({"space": "beta", "name": "Задача", "task": "Сделай"}).encode(), JS),
    ("/api/space/task", J({"space": "nope"}).encode(), JS),
    ("/api/space/task", b"{bad", JS),
    ("/api/space/task", J({"space": "beta"}).encode(), JS, "spacer"),
    ("/api/space/connect", J({"w": "@1"}).encode(), JS),
    ("/api/space/connect", J({"w": "@9"}).encode(), JS),          # окна нет — 404 (POST_W)
    ("/api/space/connect", J({}).encode(), JS),
    ("/api/space/connect", b"{bad", JS),
    ("/api/space/connect", J({"w": "@8"}).encode(), JS, "spacer"),
    ("/api/space/connect", J({"w": "@1"}).encode(), JS, "viewer"),
]
BRIDGE = [
    ("/api/bridge/devices", None, ""),
    ("/api/bridge/devices", None, "", "viewer"),
    ("/api/bridge/devices", None, "", "spacer"),
    ("/api/bridge/devices", None, "", "focus"),
    ("/api/bridge/log?id=dv1", None, ""),
    ("/api/bridge/log?id=nope", None, ""),
    ("/api/bridge/log", None, ""),
    ("/api/bridge/drafts", None, ""),
    ("/api/bridge/drafts", None, "", "spacer"),
    ("/api/bridge/pair", J({}).encode(), JS),
    ("/api/bridge/pair", b"{bad", JS),
    ("/api/bridge/pair", J({}).encode(), JS, "viewer"),
    ("/api/bridge/pair", J({}).encode(), JS, "spacer"),
    ("/api/bridge/revoke", J({"id": "dv1"}).encode(), JS),
    ("/api/bridge/revoke", J({"id": "nope"}).encode(), JS),
    ("/api/bridge/revoke", J({"id": "dv1"}).encode(), JS, "focus"),
    ("/api/bridge/private", J({"id": "dv1", "on": False}).encode(), JS),
    ("/api/bridge/private", J({"id": "dv1"}).encode(), JS),
    ("/api/bridge/private", J({"id": "nope"}).encode(), JS),
    ("/api/bridge/confirm", J({"id": "p1"}).encode(), JS),
    ("/api/bridge/confirm", J({"id": "nope"}).encode(), JS),
    ("/api/bridge/confirm", J({"id": "p1"}).encode(), JS, "origin"),   # чужой сайт — 400
    ("/api/bridge/confirm", b"{bad", JS),
    ("/api/bridge/confirm", J({"id": "p1"}).encode(), JS, "spacer"),
    ("/api/bridge/reject", J({"id": "p1"}).encode(), JS),
    ("/api/bridge/reject", J({"id": "nope"}).encode(), JS),
    ("/api/bridge/reject", J({"id": "p1"}).encode(), JS, "viewer"),
]
FOCUS = [
    ("/api/focus/list", None, ""),
    ("/api/focus/list", None, "", "viewer"),
    ("/api/focus/list", None, "", "spacer"),
    ("/api/focus/list", None, "", "focus"),
    ("/api/focus/new", J({"w": "@1", "base": "https://x", "proj": "pr1", "mode": "demo"}).encode(), JS),
    ("/api/focus/new", J({"w": "nope"}).encode(), JS),
    ("/api/focus/new", J({"space": "beta", "base": "https://x", "ttl": "1d", "max": 2, "rights": "view",
                          "name": "Клиент", "audience": "self"}).encode(), JS),
    ("/api/focus/new", J({"space": "nope"}).encode(), JS),
    ("/api/focus/new", J({"space": "beta", "max": 0}).encode(), JS),
    ("/api/focus/new", b"{bad", JS),
    ("/api/focus/new", J({"space": "beta"}).encode(), JS, "spacer"),
    ("/api/focus/new", J({"w": "@1"}).encode(), JS, "viewer"),
    ("/api/focus/new", J({"w": "@5"}).encode(), JS, "focus"),
    ("/api/focus/send", J({"url": "https://x/#focus=t"}).encode(), JS),
    ("/api/focus/send", J({"url": "nope"}).encode(), JS),
    ("/api/focus/qr", J({"url": "https://x/#focus=t"}).encode(), JS),
    ("/api/focus/qr", J({"url": "nope"}).encode(), JS),
    ("/api/focus/qr", J({}).encode(), JS),                 # без url — 404 (KeyError из b["url"], как в цепочке)
    ("/api/focus/browser", J({"id": "f1", "on": False}).encode(), JS),
    ("/api/focus/browser", J({"id": "nope"}).encode(), JS),
    ("/api/focus/revoke", J({"id": "f1"}).encode(), JS),
    ("/api/focus/revoke", J({"id": "nope"}).encode(), JS),
    ("/api/focus/revoke", b"{bad", JS),
    ("/api/focus/revoke", J({"id": "f1"}).encode(), JS, "spacer"),
    # свой компьютер по фокус-ссылке (focus_bridge): только с «Браузером» и только устройства этой ссылки
    ("/api/focus/bridge", None, "", "focusb"),
    ("/api/focus/bridge", None, "", "focus"),              # «Браузер» не разрешён — 403
    ("/api/focus/bridge", None, ""),                       # обычной панели такого пути нет — 404
    ("/api/focus/bridge/pair", J({}).encode(), JS, "focusb"),
    ("/api/focus/bridge/pair", J({}).encode(), JS, "focus"),
    ("/api/focus/bridge/pair", J({}).encode(), JS),
    ("/api/focus/bridge/revoke", J({"id": "dv1"}).encode(), JS, "focusb"),
    ("/api/focus/bridge/revoke", J({"id": "dv2"}).encode(), JS, "focusb"),   # чужое устройство — 403
    ("/api/focus/bridge/revoke", b"{bad", JS, "focusb"),
    ("/api/focus/bridge/private", J({"id": "dv1", "on": False}).encode(), JS, "focusb"),
    ("/api/focus/bridge/private", J({"id": "dv2"}).encode(), JS, "focusb"),
    ("/api/focus/bridge/private", J({"id": "dv1"}).encode(), JS, "spacer"),
]
# Снимки — код до переноса (origin/refactor/routes-models-integr, 31569e8): владелец, наблюдатель, человек
# пространства A с данными пространства B, фокус-ссылки (сессия, проект, «Браузер»), /api/v1 (группа «sessions»).
# «now» и «build» — часы и версия страницы — в снимке нулями.
WIDE = {"projects": PROJECTS, "spaces": SPACES, "bridge": BRIDGE, "focus": FOCUS}


HOME = os.path.expanduser("~")                   # домашняя папка машины — в снимке «~» (CI и сервер разные)


def _still(x):
    if isinstance(x, dict):
        return {k: 0 if k in ("now", "build") else _still(v) for k, v in x.items()}
    if isinstance(x, str):
        return x.replace(HOME, "~") if HOME not in ("", "/") else x
    return [_still(v) for v in x] if isinstance(x, list) else x


@pytest.mark.parametrize("area", WIDE)
def test_border_routes_answer_as_before(wide, area):
    got = _still(json.loads(json.dumps(snap_of(wide, WIDE[area]))))
    assert got == json.loads((FIX / f"routes_{area}_snap.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------- люди и вход, команды и терминал: права и куки.
# Кто спрашивает: без входа («anon»), наблюдатель, участник, админ, гость без Telegram, человек пространства A,
# гость фокус-ссылки, ссылка на пространство (действующая и погасшая), свежий вход без кода подтверждения («fresh»),
# Mini App («tgh»). В снимке — и Set-Cookie (имя и атрибуты; значение — «*»). Команды и терминал — только на
# подделках (Panel.command_*, run, term_run, tty_window и termwin.*): ничего не выполняется, tmux не трогается.
MEMBER, ADMIN, GUEST = 4, 6, -(10 ** 15) - 5
SLREC = {"id": "00000000000a", "mode": "space", "space": "alpha", "aud": "self", "name": "Клиент", "exp": 0,
         "forever": True, "rights": "full"}


@pytest.fixture
def ppl(wide, monkeypatch):
    from gas_pult import invites, termwin
    p, rec, ok = wide["p"], wide["rec"], wide["ok"]
    for uid, role, name in ((MEMBER, "member", "Участник"), (ADMIN, "admin", "Админ"), (GUEST, "member", "Гость")):
        p.people.add(uid, role, name)
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
        wide[{MEMBER: "member", ADMIN: "admin", GUEST: "guest"}[uid]] = p.auth.issue(uid)
    wide["fresh"] = fresh = p.auth.issue(OWNER)          # свежий вход владельца: код подтверждения ещё не введён
    monkeypatch.setattr(p.auth, "needs_confirm", lambda tok, *a, **k: tok == fresh)
    vu = focus.vuid(SLREC["id"])
    monkeypatch.setattr(p.focus, "space_by_cookie", lambda c: SLREC if c == "sl1" else
                        (_ for _ in ()).throw(focus.Gone("ссылка отозвана")) if c == "sl2" else None)
    monkeypatch.setattr(p.people, "virtual", lambda uid: {"role": "member", "tenant": "alpha"} if uid == vu else None)
    p.people.accept(vu)
    fakes = {"country_info": {"chosen": "NL"}, "set_country": ok({"chosen": "NL"}), "set_ui": ok({"persona": "x"}),
             "team_info": {"people": [{"id": VIEWER}, {"id": MEMBER}]}, "people_list": [{"id": VIEWER}],
             "set_role": ok(None), "admin_may": ok({"id": VIEWER}), "forget_person": ok(None), "set_access": ok(None),
             "feedback_add": ok({"ok": True}), "help_ask": ok({"answer": "так"}), "key_label": "Владелец",
             "confirm_start": ok({"id": "c1"}), "confirm_done": ok(None), "invite_qr": ok(b"PNG"),
             "device_link": ok({"path": "/invite/d1"}), "call_help": ok({"ok": True}), "bot_username": "pult_bot",
             "ui": rec("ui", p.ui), "prefs": rec("prefs", p.prefs), "is_owner": rec("is_owner", p.is_owner),
             # команды и терминал — подделки: ничего не выполняется
             "command_log": {"items": [{"id": "c1"}]}, "command_run": ok({"ok": True}),
             "command_mark": ok({"ok": True}), "command_term": ok({"ok": True, "id": "gp"}),
             "run": ok({"ok": True, "out": "готово"}), "term_run": ok({"ok": True, "id": "gp"}),
             "tty_window": lambda wid, *a, **k: ok(None)(wid) or {"id": wid, "path": "/tmp/m",
                                                                  "name": termwin.WINDOW if wid == "@6" else "bash"},
             "tty_kind": "shell"}
    for name, out in fakes.items():
        monkeypatch.setattr(p, name, out if name in ("ui", "prefs", "is_owner") else rec(name, out))
    subs = {"people": {"set_prefs": ok({"lang": "en"}), "tour": {"main": "done"}, "set_tour": ok({"main": "done"})},
            "team": {"set": ok(None)}, "uses": {"record": 1},
            "keys": {"info": {"keys": []}, "register_options": ok({"challenge": "c"}),
                     "register_verify": ok([{"id": "k1"}]), "remove": ok([])},
            "oidc": {"info": {"google": False}, "ticket": ok("T1"), "unlink": ok({"ok": True})},
            "email": {"info": {"email": ""}, "bind_start": ok({"sent": True}), "bind_confirm": ok({"ok": True}),
                      "unbind": {"ok": True}, "options": ok({"ok": True})},
            "helper": {"feedback": ok({"ok": True}), "ask": {"answer": "вход"}, "who_key": "ip:x"},
            "auth": {"confirm_verify": ok(None), "logout": None},
            "geo": {"info": {"geo": True}}, "logins": {"start": ("r1", "n1")},
            "journal": {"output": lambda i: None if i == "nope" else "вывод"},
            "pult": {"set_state": None, "cost_decide": None, "module_root": "/tmp/mod"}}
    for obj, names in subs.items():
        for name, out in names.items():
            monkeypatch.setattr(getattr(p, obj), name, rec(f"{obj}.{name}", out))
    monkeypatch.setattr(p.pult.deliv, "record", rec("deliv.record", None))
    monkeypatch.setattr(invites, "new", rec("invites.new", ok({"code": "C1", "short": "123456", "hint": "h"})))
    for name, out in {"screen": ok({"lines": ["$"]}), "history": ok({"lines": ["$ ls"], "start": 0}),
                      "type_line": ok(None), "key": ok(None), "close": ok(None), "tty_size": ok({"cols": 80}),
                      "tty_key": ok(None), "tty_type": ok(None)}.items():
        monkeypatch.setattr(termwin, name, rec(f"termwin.{name}", out))
    wide["cookies"] = True
    return wide


PEOPLE = [
    ("/api/terms", None, ""),
    ("/api/terms", None, "", "anon"),                     # без входа — 401
    ("/api/terms", None, "", "viewer"),
    ("/api/terms", None, "", "slink"),
    ("/api/terms", None, "", "slinkg"),                   # погасшая ссылка — 410
    ("/api/terms", None, "", "focus"),
    ("/api/prefs", None, ""),
    ("/api/prefs", None, "", "viewer"),
    ("/api/prefs", None, "", "spacer"),
    ("/api/prefs", None, "", "slink"),
    ("/api/prefs", None, "", "anon"),
    ("/api/persona", None, ""),
    ("/api/persona", None, "", "member"),
    ("/api/team", None, ""),
    ("/api/team", None, "", "viewer"),
    ("/api/team", None, "", "admin"),
    ("/api/tour", None, ""),
    ("/api/tour", None, "", "guest"),
    ("/api/country", None, ""),
    ("/api/country", None, "", "viewer"),
    ("/api/email", None, ""),
    ("/api/email", None, "", "member"),
    ("/api/email", None, "", "slink"),
    ("/api/passkeys", None, ""),
    ("/api/passkeys", None, "", "viewer"),
    ("/api/passkeys", None, "", "slink"),
    ("/api/oidc", None, ""),
    ("/api/oidc", None, "", "guest"),
    ("/api/people", None, ""),
    ("/api/people", None, "", "viewer"),
    ("/api/people", None, "", "member"),
    ("/api/people", None, "", "admin"),
    ("/api/invite/qr?u=https%3A%2F%2Fx%2Finvite%2Fabc", None, ""),
    ("/api/invite/qr?u=nope", None, ""),
    ("/api/invite/qr?u=https%3A%2F%2Fx%2Finvite%2Fabc", None, "", "member"),
    ("/api/invite/qr?u=https%3A%2F%2Fx%2Finvite%2Fabc", None, "", "spacer"),
    ("/api/invite/qr?u=https%3A%2F%2Fx%2Finvite%2Fabc", None, "", "admin"),
    ("/api/clientlog", J({"kind": "error", "msg": "m", "at": "a.js:1", "screen": "home", "mid": "x1"}).encode(), JS),
    ("/api/clientlog", J({"kind": "error"}).encode(), JS, "anon"),
    ("/api/clientlog", J({"kind": "error"}).encode(), JS, "viewer"),
    ("/api/clientlog", b"{bad", JS),
    ("/api/uses", J({"ids": ["home"]}).encode(), JS),
    ("/api/uses", J({"ids": "home"}).encode(), JS),
    ("/api/uses", J({"ids": ["home"]}).encode(), JS, "viewer"),
    ("/api/prefs", J({"simple": True}).encode(), JS),     # владелец — простой режим нельзя (400)
    ("/api/prefs", J({"lang": "en", "rate": 1.5}).encode(), JS),
    ("/api/prefs", J({"rate": "x"}).encode(), JS),
    ("/api/prefs", J({"rate": True}).encode(), JS),
    ("/api/prefs", J({"simple": True}).encode(), JS, "member"),
    ("/api/prefs", J({"simple": False, "lang": "ru"}).encode(), JS, "viewer"),
    ("/api/prefs", J({"lang": "ru"}).encode(), JS, "slink"),
    ("/api/prefs", b"{bad", JS),
    ("/api/persona", J({"persona": "developer"}).encode(), JS),
    ("/api/persona", J({"persona": "bad"}).encode(), JS, "viewer"),
    ("/api/persona", J({"persona": "developer"}).encode(), JS, "member"),
    ("/api/team", J({"caps": ["cap.a"], "sections": ["s"]}).encode(), JS),
    ("/api/team", J({"id": 999}).encode(), JS),            # не сотрудник — 400
    ("/api/team", J({"id": VIEWER, "reset": True}).encode(), JS),
    ("/api/team", J({"id": "x"}).encode(), JS),
    ("/api/team", J({"caps": ["cap.a"]}).encode(), JS, "viewer"),
    ("/api/team", J({"caps": ["cap.a"]}).encode(), JS, "admin"),
    ("/api/terms/accept", J({"version": "0"}).encode(), JS),   # старая версия — 400
    ("/api/terms/accept", J({"version": terms.VERSION}).encode(), JS, "viewer"),
    ("/api/terms/accept", J({"version": "0"}).encode(), JS, "anon"),
    ("/api/terms/accept", J({"version": "0"}).encode(), JS, "slink"),
    ("/api/country", J({"code": "NL"}).encode(), JS),
    ("/api/country", J({"code": "bad"}).encode(), JS, "viewer"),
    ("/api/feedback", J({"text": "Отзыв"}).encode(), JS),
    ("/api/feedback", J({"text": "bad"}).encode(), JS, "viewer"),
    ("/api/feedback", J({"text": "Отзыв"}).encode(), JS, "anon"),
    ("/api/tour", J({"tour": "main", "state": "done"}).encode(), JS),
    ("/api/tour", J({"tour": "bad"}).encode(), JS, "guest"),
    ("/api/passkeys/options", J({}).encode(), JS),
    ("/api/passkeys/options", J({}).encode(), JS, "viewer"),
    ("/api/passkeys/options", J({}).encode(), JS, "slink"),   # по ссылке на пространство — нет (SLINK_NO)
    ("/api/passkeys/add", J({"id": "k1", "credential": {"a": 1}, "name": "Мак"}).encode(), JS),
    ("/api/passkeys/add", J({"id": "bad"}).encode(), JS),
    ("/api/passkeys/add", b"{bad", JS),
    ("/api/passkeys/remove", J({"id": "k1"}).encode(), JS),
    ("/api/passkeys/remove", J({"id": "nope"}).encode(), JS, "member"),
    ("/api/oidc/link", J({"provider": "google"}).encode(), JS),
    ("/api/oidc/link", J({"provider": "bad"}).encode(), JS),
    ("/api/oidc/link", J({"provider": "google"}).encode(), JS, "guest"),
    ("/api/oidc/unlink", J({"provider": "google"}).encode(), JS),
    ("/api/oidc/unlink", J({"provider": "nope"}).encode(), JS),
    ("/api/email/bind", J({"email": "a@b.test"}).encode(), JS),
    ("/api/email/bind", J({"email": "bad"}).encode(), JS, "viewer"),
    ("/api/email/confirm", J({"email": "a@b.test", "code": "123456"}).encode(), JS),
    ("/api/email/confirm", J({"email": "a@b.test", "code": "bad"}).encode(), JS),
    ("/api/email/remove", J({}).encode(), JS),
    ("/api/email/options", J({"second_factor": True, "notify": False}).encode(), JS),
    ("/api/email/options", J({"second_factor": "bad"}).encode(), JS),
    ("/api/help/ask", J({"q": "как войти", "ctx": "home"}).encode(), JS),
    ("/api/help/ask", J({"q": "bad"}).encode(), JS, "viewer"),
    ("/api/help/ask", J({"q": "как войти"}).encode(), JS, "anon"),     # экран входа — help_anon, до permit
    ("/api/help/feedback", J({"id": "h1", "useful": True, "action": "a"}).encode(), JS),
    ("/api/help/feedback", J({"id": "h1", "useful": False}).encode(), JS, "admin"),   # админ — как участник
    ("/api/help/feedback", J({"id": "nope"}).encode(), JS, "viewer"),
    ("/api/confirm/start", J({}).encode(), JS, "fresh"),
    ("/api/confirm/check", J({}).encode(), JS, "fresh"),
    ("/api/confirm/check", J({}).encode(), JS),
    ("/api/confirm/verify", J({"id": "c1", "code": "123456"}).encode(), JS, "fresh"),
    ("/api/confirm/verify", J({"id": "nope", "code": "1"}).encode(), JS, "fresh"),
    ("/api/confirm/verify", b"{bad", JS, "fresh"),
    ("/api/confirm/start", J({}).encode(), JS, "slink"),   # не браузерный вход — 400
    ("/api/confirm/start", J({}).encode(), JS, "focus"),
    ("/api/confirm/check", J({}).encode(), JS, "anon"),
    ("/api/people/role", J({"id": VIEWER, "role": "member"}).encode(), JS),
    ("/api/people/role", J({"id": "x"}).encode(), JS),
    ("/api/people/role", J({"id": VIEWER, "role": "bad"}).encode(), JS, "admin"),
    ("/api/people/role", J({"id": VIEWER, "role": "member"}).encode(), JS, "member"),
    ("/api/people/remove", J({"id": VIEWER}).encode(), JS),
    ("/api/people/remove", J({"id": "nope"}).encode(), JS, "admin"),
    ("/api/people/remove", J({"id": VIEWER}).encode(), JS, "viewer"),
    ("/api/people/access", J({"id": VIEWER, "days": 30}).encode(), JS),
    ("/api/people/access", J({"id": VIEWER, "days": "x"}).encode(), JS, "admin"),
    ("/api/invite/new", J({"space": "alpha", "role": "member", "ttl": "1d", "uses": 2, "access": 30, "plan": "p",
                           "name": "Иван"}).encode(), JS),
    ("/api/invite/new", J({"ttl": "9y"}).encode(), JS),
    ("/api/invite/new", J({"space": "bad"}).encode(), JS),
    ("/api/invite/new", J({"uses": "x"}).encode(), JS),
    ("/api/invite/new", b"{bad", JS),
    ("/api/invite/new", J({}).encode(), JS, "member"),
    ("/api/invite/new", J({}).encode(), JS, "viewer"),
    ("/api/invite/device", J({}).encode(), JS),
    ("/api/invite/device", J({"id": VIEWER}).encode(), JS),
    ("/api/invite/device", J({"id": VIEWER}).encode(), JS, "admin"),
    ("/api/invite/device", J({"id": VIEWER}).encode(), JS, "member"),   # не владелец — ссылка себе
    ("/api/invite/device", J({}).encode(), JS, "viewer"),
    ("/api/invite/device", J({}).encode(), JS, "slink"),
    ("/api/link/tg", J({}).encode(), JS),                   # Telegram уже привязан — 400
    ("/api/link/tg", J({}).encode(), JS, "guest"),
    ("/api/link/tg", J({}).encode(), JS, "anon"),
    ("/api/help/call", J({"w": "@1"}).encode(), JS),
    ("/api/help/call", J({"w": "@9"}).encode(), JS),        # окна нет — 404 (POST_W)
    ("/api/help/call", J({}).encode(), JS),
    ("/api/help/call", b"{bad", JS),
    ("/api/help/call", J({"w": "@5"}).encode(), JS, "spacer"),
    ("/api/help/call", J({"w": "@1"}).encode(), JS, "viewer"),
    ("/api/logout", J({}).encode(), JS, "slink"),           # ссылка на пространство: cookie фокуса стирается
    ("/api/logout", J({}).encode(), JS, "slinkg"),
    ("/api/logout", J({}).encode(), JS, "focus"),           # фокус-ссылка: своя ветка focus_do
    ("/api/logout", J({}).encode(), JS, "anon"),
    ("/api/logout", b"{bad", JS, "viewer"),
    ("/api/logout", J({}).encode(), JS, "viewer"),          # вход стирается: cookie gp_… с Max-Age=0
    ("/api/logout", J({}).encode(), JS),
]
CMDS = [
    ("/api/commands", None, ""),
    ("/api/commands", None, "", "viewer"),
    ("/api/commands", None, "", "member"),
    ("/api/commands", None, "", "spacer"),
    ("/api/commands", None, "", "anon"),
    ("/api/commands/output?id=c1", None, ""),
    ("/api/commands/output?id=nope", None, ""),             # вывода уже нет — 404
    ("/api/commands/output?id=c1", None, "", "viewer"),
    ("/api/term?id=gp", None, ""),
    ("/api/term?id=nope", None, ""),
    ("/api/term?id=gp", None, "", "viewer"),
    ("/api/term?id=gp", None, "", "focus"),
    ("/api/tty?w=%405&start=0&end=10&all=1&color=1", None, ""),
    ("/api/tty?w=nope", None, ""),
    ("/api/tty?w=%405", None, "", "viewer"),
    ("/api/tty?w=%405", None, "", "member"),
    ("/api/tty?w=%407", None, "", "spacer"),
    ("/api/tty?w=%405", None, "", "slink"),
    ("/api/commands/run", J({"id": "c1", "confirmed": True}).encode(), JS),
    ("/api/commands/run", J({"id": "nope"}).encode(), JS),
    ("/api/commands/run", b"{bad", JS),
    ("/api/commands/run", J({"id": "c1"}).encode(), JS, "fresh"),   # свежий вход — сначала код (403 confirm)
    ("/api/commands/run", J({"id": "c1"}).encode(), JS, "viewer"),
    ("/api/commands/run", J({"id": "c1"}).encode(), JS, "member"),
    ("/api/commands/mark", J({"id": "c1", "done": False}).encode(), JS),
    ("/api/commands/mark", J({"id": "c1"}).encode(), JS),
    ("/api/commands/mark", J({"id": "nope"}).encode(), JS, "viewer"),
    ("/api/commands/term", J({"id": "c1", "confirmed": True}).encode(), JS),
    ("/api/commands/term", J({"id": "nope"}).encode(), JS),
    ("/api/commands/term", J({"id": "c1"}).encode(), JS, "fresh"),
    ("/api/term/type", J({"id": "gp", "text": "пароль"}).encode(), JS),
    ("/api/term/type", J({"id": "gp", "text": "пароль"}).encode(), JS, "tgh"),   # из Mini App — 400
    ("/api/term/type", J({"id": "nope"}).encode(), JS),
    ("/api/term/type", J({"id": "gp"}).encode(), JS, "viewer"),
    ("/api/term/type", J({"id": "gp"}).encode(), JS, "fresh"),
    ("/api/term/key", J({"id": "gp", "key": "C-c"}).encode(), JS),
    ("/api/term/key", J({"id": "gp", "key": "bad"}).encode(), JS),
    ("/api/term/close", J({"id": "gp"}).encode(), JS),
    ("/api/term/close", J({"id": "nope"}).encode(), JS),
    ("/api/term/close", b"{bad", JS),
    ("/api/tty/type", J({"w": "@5", "text": "ls"}).encode(), JS),
    ("/api/tty/type", J({"w": "@6", "text": "пароль"}).encode(), JS, "tgh"),     # окно с паролем из Mini App — 400
    ("/api/tty/type", J({"w": "@5", "text": "ls"}).encode(), JS, "tgh"),
    ("/api/tty/type", J({"w": "nope"}).encode(), JS),
    ("/api/tty/type", J({"w": "@5", "text": "ls"}).encode(), JS, "member"),
    ("/api/tty/type", J({"w": "@7", "text": "ls"}).encode(), JS, "spacer"),
    ("/api/tty/key", J({"w": "@5", "key": "Enter"}).encode(), JS),
    ("/api/tty/key", J({"w": "@5", "key": "bad"}).encode(), JS),
    ("/api/tty/key", J({"w": "@5", "key": "Enter"}).encode(), JS, "viewer"),
    ("/api/tty/size", J({"w": "@5", "cols": 80, "rows": 24, "reset": True}).encode(), JS),
    ("/api/tty/size", J({"w": "nope"}).encode(), JS),
    ("/api/tty/size", b"{bad", JS),
    ("/api/run", J({"w": "@1", "i": 0, "sha": "abc", "confirmed": True}).encode(), JS),
    ("/api/run", J({"w": "@9", "i": 0}).encode(), JS),      # окна нет — 404 (POST_W)
    ("/api/run", J({"i": 0}).encode(), JS),
    ("/api/run", J({"w": "@1", "i": "x"}).encode(), JS),
    ("/api/run", J({"w": "@1", "sha": "bad"}).encode(), JS),
    ("/api/run", b"{bad", JS),
    ("/api/run", J({"w": "@1", "i": 0}).encode(), JS, "fresh"),
    ("/api/run", J({"w": "@1", "i": 0}).encode(), JS, "viewer"),
    ("/api/run", J({"w": "@5", "i": 0, "sha": "abc"}).encode(), JS, "focus"),
    ("/api/run", J({"w": "@1", "i": 0}).encode(), JS, "focus"),   # не окно ссылки — 403
    ("/api/run/term", J({"w": "@1", "i": 1, "sha": "s", "confirmed": True}).encode(), JS),
    ("/api/run/term", J({"w": "@9", "i": 1}).encode(), JS),
    ("/api/run/term", J({"w": "@1", "sha": "bad"}).encode(), JS),
    ("/api/run/term", J({"w": "@1", "i": 1}).encode(), JS, "fresh"),
    ("/api/run/term", J({"w": "@5", "i": 1, "sha": "s"}).encode(), JS, "focus"),
]
# Снимки — код до переноса (origin/refactor/routes-proj-space-bridge, e5a8f06): «at» (время согласия) — нулём.
PPL = {"people": PEOPLE, "cmds": CMDS}


def _still_at(x):
    if isinstance(x, dict):
        return {k: 0 if k == "at" else _still_at(v) for k, v in x.items()}
    return [_still_at(v) for v in x] if isinstance(x, list) else x


def ppl_snap(srv, cases) -> dict:
    """Снимок: токены сессий в вызовах (``auth.logout``, ``confirm_*``) — именем входа, не значением; User-Agent
    клиента (версия Python) — «<ua>»; домашняя папка, часы и версия — как в ``_still``."""
    txt = json.dumps(snap_of(srv, cases), ensure_ascii=False)
    for name in ("tok", "viewer", "member", "admin", "guest", "fresh", "spacer"):
        txt = txt.replace(srv[name], f"<{name}>")
    txt = re.sub(r"Python-urllib/[0-9.]+", "<ua>", txt)
    return _still_at(_still(json.loads(txt)))


@pytest.mark.parametrize("area", PPL)
def test_people_and_commands_answer_as_before(ppl, area):
    assert ppl_snap(ppl, PPL[area]) == json.loads((FIX / f"routes_{area}_snap.json").read_text(encoding="utf-8"))
