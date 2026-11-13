"""Вход не слетает (задание штаба 13.11: «периодически просят авторизоваться»).

Причины: 1) в Mini App каждый запрос проверялся только подписью Telegram ``initData``, а она действует сутки
(``webapp.MAX_AGE``) — окно Mini App, открытое дольше, получало 401 и показывало вход; cookie не выдавалась;
2) cookie браузера жила ровно 30 дней от входа и не продлевалась. Сессии в файле — перезапуск службы их не теряет
(проверяем настоящим HTTP-сервером: «до» и «после» — разные процессы-объекты ``Panel``)."""

import hashlib
import hmac
import json
import multiprocessing
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import webapp, webauth
from gas_pult.config import Config

TOKEN = "1:T"


def signed(uid: int, auth_date: float) -> str:
    fields = {"auth_date": str(int(auth_date)), "query_id": "q", "user": json.dumps({"id": uid, "first_name": "Г"})}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    return urllib.parse.urlencode({**fields, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()})


# ---------- срок сессии ----------
def test_session_survives_new_auth_object(tmp_path):
    tok = webauth.Auth(tmp_path / "s.json").issue(7, "UA")
    assert webauth.Auth(tmp_path / "s.json").uid(tok) == 7        # «перезапуск» — новый объект, тот же файл


def test_sliding_expiry(tmp_path):
    a = webauth.Auth(tmp_path / "s.json")
    tok = a.issue(7)
    now = time.time()
    assert a.touch(tok, now) is False                             # только что выдана — продлевать рано
    day40 = now + 25 * 86400                                      # заходит через 25 дней — срок снова 30
    assert a.touch(tok, day40) is True
    exp = json.loads((tmp_path / "s.json").read_text())[webauth._h(tok)]["exp"]
    assert exp == pytest.approx(day40 + webauth.SESSION_TTL, abs=1)
    assert a.touch(tok, day40 + 3600) is False                    # раз в сутки, не на каждый запрос
    assert a.touch(tok, exp + 1) is False                         # истёкшую не оживляем
    assert a.touch("", now) is False and a.touch("чужой", now) is False


def _issue_many(path, n, q):
    a = webauth.Auth(path)
    q.put([a.issue(1000 + i) for i in range(n)])


@pytest.mark.filterwarnings("ignore::DeprecationWarning")   # fork при живых потоках pytest — здесь безопасно
def test_two_processes_do_not_lose_sessions(tmp_path):
    """Сессии пишут и панель, и бот (разные процессы): без файлового замка одна запись затирала другую."""
    path = tmp_path / "s.json"
    ctx = multiprocessing.get_context("fork")
    q = ctx.Queue()
    ps = [ctx.Process(target=_issue_many, args=(path, 25, q)) for _ in range(3)]
    for p in ps:
        p.start()
    toks = [t for _ in ps for t in q.get(timeout=30)]
    for p in ps:
        p.join(10)
    a = webauth.Auth(path)
    assert len(toks) == 75 and all(a.uid(t) is not None for t in toks)


# ---------- настоящий HTTP: перезапуск службы, Mini App ----------
def start(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    p = webapp.Panel(Config(token=TOKEN, owners=[1]))
    p.people.accept(1)
    p.people.set_country(1, chosen="NL")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return p, srv, f"http://127.0.0.1:{srv.server_address[1]}"


def get(base, path, cookie="", init=""):
    h = {}
    if cookie:
        h["Cookie"] = f"{webauth.COOKIE}={cookie}"
    if init:
        h["X-Telegram-Init-Data"] = init
    req = urllib.request.Request(base + path, headers=h)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.headers.get("Set-Cookie") or ""
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Set-Cookie") or ""


def tok_of(set_cookie: str) -> str:
    return set_cookie.split(";")[0].partition("=")[2]


def test_restart_of_service_keeps_login(tmp_path, monkeypatch):
    p, srv, base = start(tmp_path, monkeypatch)
    tok = p.auth.issue(1, "Mozilla")
    assert get(base, "/api/meta", tok)[0] == 200
    srv.shutdown()
    srv.server_close()
    _p2, srv2, base2 = start(tmp_path, monkeypatch)                   # служба перезапущена: новый процесс-объект
    try:
        assert get(base2, "/api/meta", tok)[0] == 200
        assert get(base2, "/api/meta", "wrong-token")[0] == 401
    finally:
        srv2.shutdown()


def test_mini_app_gets_cookie_and_keeps_working_after_init_data_expires(tmp_path, monkeypatch):
    p, srv, base = start(tmp_path, monkeypatch)
    try:
        code, sc = get(base, "/api/meta", init=signed(1, time.time()))
        assert code == 200 and sc.startswith(webauth.COOKIE + "=") and "HttpOnly" in sc and "Secure" in sc
        tok = tok_of(sc)
        assert p.auth.uid(tok) == 1
        stale = signed(1, time.time() - 2 * webapp.MAX_AGE)          # Mini App открыт двое суток
        assert get(base, "/api/sessions", init=stale)[0] == 401        # одной подписью — нельзя (как и было)
        assert get(base, "/api/sessions", tok, init=stale)[0] == 200   # с cookie — работает, вход не просим
        code, sc2 = get(base, "/api/meta", tok, init=signed(1, time.time()))
        assert code == 200 and sc2 == ""                               # cookie уже есть — новую не выдаём
        n = len(json.loads((p.cfg.data / "web_sessions.json").read_text()))
        for _ in range(5):                                             # cookie не возвращается (iframe) — не плодим
            get(base, "/api/meta", init=signed(1, time.time()))
        assert len(json.loads((p.cfg.data / "web_sessions.json").read_text())) == n
    finally:
        srv.shutdown()


def test_cookie_is_renewed_on_activity(tmp_path, monkeypatch):
    p, srv, base = start(tmp_path, monkeypatch)
    try:
        tok = p.auth.issue(1)
        d = json.loads((p.cfg.data / "web_sessions.json").read_text())
        d[webauth._h(tok)]["exp"] = time.time() + 2 * 86400            # осталось 2 дня
        (p.cfg.data / "web_sessions.json").write_text(json.dumps(d))
        code, sc = get(base, "/api/meta", tok)
        assert code == 200 and tok_of(sc) == tok and f"Max-Age={webauth.SESSION_TTL}" in sc
        exp = json.loads((p.cfg.data / "web_sessions.json").read_text())[webauth._h(tok)]["exp"]
        assert exp > time.time() + 29 * 86400
        assert get(base, "/api/meta", tok)[1] == ""                    # второй запрос — без лишней Set-Cookie
    finally:
        srv.shutdown()


def test_unknown_telegram_user_gets_no_cookie(tmp_path, monkeypatch):
    _p, srv, base = start(tmp_path, monkeypatch)
    try:
        code, sc = get(base, "/api/meta", init=signed(999, time.time()))
        assert code == 401 and sc == ""                                # роли нет — ни входа, ни cookie
    finally:
        srv.shutdown()
