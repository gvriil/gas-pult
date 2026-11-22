"""Подтверждение кодом (аудит 09.11): новая сессия браузера выполняет команды и пишет в терминал только после кода.

Старая сессия (моложе суток — новая) и Mini App в Telegram — сразу. Код — в Telegram бота (или на почту, если у
человека включён второй фактор), живёт 10 минут, привязан к своей сессии."""

import json
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import webapp, webauth
from gas_pult.config import Config
from gas_pult.panel import work

RUN = {"w": "@1", "i": 0, "sha": "aaa"}


@pytest.fixture
def server(monkeypatch, tmp_path):
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.add(2, "member", "Иван")
    for uid in (1, 2):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    sent = []
    monkeypatch.setattr(p.pult, "api", lambda method, **kw: sent.append(kw) or {})
    monkeypatch.setattr(p, "commands", lambda w: [{"i": 0, "cmd": "ls", "kind": "local", "danger": False,
                                                   "sha": "aaa"}])
    monkeypatch.setattr(p, "window", lambda wid: {"id": wid, "path": str(tmp_path), "cmd": "claude", "name": "a"})
    monkeypatch.setattr(work, "execute", lambda cmd, cwd: (0, 0.1, f"ran {cmd}"))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield p, f"http://127.0.0.1:{srv.server_address[1]}", sent
    srv.shutdown()


def call(base, path, body=None, tok="", headers=None):
    h = {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={tok}" if tok else "", **(headers or {})}
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, h)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def code_in(text: str) -> str:
    return re.search(r"Код: (\d{6})", text).group(1)


def test_new_session_needs_code_then_runs(server):
    p, base, sent = server
    tok = p.auth.issue(1)
    code, d = call(base, "/api/run", RUN, tok)
    assert code == 403 and d["confirm"] == "code" and d["code"] == "confirm"
    code, d = call(base, "/api/confirm/start", {}, tok, {"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/130"})
    assert code == 200 and d["via"] == "telegram" and d["ttl"] == webauth.CONFIRM_TTL
    assert sent[-1]["chat_id"] == 1 and "Windows · Chrome" in sent[-1]["text"]   # владельцу: код и откуда
    good = code_in(sent[-1]["text"])
    bad = "000000" if good != "000000" else "111111"
    code, e = call(base, "/api/confirm/verify", {"id": d["id"], "code": bad}, tok)
    assert code == 400 and "неверный код" in e["error"]
    assert call(base, "/api/run", RUN, tok)[0] == 403                              # неверный код — всё ещё нельзя
    assert call(base, "/api/confirm/verify", {"id": d["id"], "code": good}, tok) == (200, {"ok": True})
    code, d = call(base, "/api/run", RUN, tok)
    assert code == 200 and d["out"] == "ran ls"
    assert call(base, "/api/confirm/verify", {"id": "x", "code": good}, tok)[0] == 400   # код одноразовый


def test_old_session_runs_at_once(server):
    p, base, sent = server
    tok = p.auth.issue(1)
    d = json.loads(p.auth.store.read_text())
    d[webauth._h(tok)]["created"] = time.time() - webauth.CONFIRM_FRESH - 60     # вход больше суток назад
    p.auth.store.write_text(json.dumps(d))
    assert call(base, "/api/run", RUN, tok)[0] == 200 and sent == []
    del d[webauth._h(tok)]["created"]                                            # сессия до этой отметки — старая
    p.auth.store.write_text(json.dumps(d))
    assert call(base, "/api/run", RUN, tok)[0] == 200


def test_all_confirm_paths_blocked_for_new_session(server):
    p, base, _ = server
    tok = p.auth.issue(1)
    for path in sorted(webapp.CONFIRM):
        code, d = call(base, path, {"w": "@1", "id": "@9", "i": 0, "sha": "aaa", "text": "x", "key": "Enter"}, tok)
        assert code == 403 and d.get("confirm") == "code", path
    assert call(base, "/api/meta", tok=tok)[0] == 200                              # остальное — как было
    assert {"/api/run", "/api/commands/run", "/api/term/type", "/api/tty/type"} <= webapp.CONFIRM


def test_code_bound_to_its_session(server):
    p, base, sent = server
    a, b = p.auth.issue(1), p.auth.issue(1)
    d = call(base, "/api/confirm/start", {}, a)[1]
    good = code_in(sent[-1]["text"])
    assert call(base, "/api/confirm/verify", {"id": d["id"], "code": good}, b)[0] == 400
    assert call(base, "/api/run", RUN, b)[0] == 403                              # чужой сессии код не подходит
    assert p.auth.needs_confirm(a) and p.auth.needs_confirm(b)
    assert call(base, "/api/confirm/verify", {"id": d["id"], "code": good}, a)[0] == 200   # своей — подходит
    assert not p.auth.needs_confirm(a) and p.auth.needs_confirm(b)


def test_telegram_mini_app_is_trusted(server, monkeypatch):
    _p, base, sent = server
    monkeypatch.setattr(webapp, "verify", lambda init, token, now=None: {"id": 1, "first_name": "Владелец"}
                        if init else None)
    tg = {"X-Telegram-Init-Data": "query_id=1"}
    assert call(base, "/api/run", RUN, headers=tg)[0] == 200
    code, d = call(base, "/api/confirm/start", {}, headers=tg)
    assert code == 400 and "браузера" in d["error"] and sent == []


def test_member_gets_code_in_own_telegram(server):
    p, base, sent = server
    tok = p.auth.issue(2)
    assert call(base, "/api/confirm/start", {}, tok)[1]["via"] == "telegram"
    assert sent[-1]["chat_id"] == 2


def test_owner_code_session_goes_to_owners(server):
    p, base, sent = server
    rid, code = p.auth.start()
    tok = p.auth.verify(rid, code)                                               # вход кодом владельцу (LEGACY)
    call(base, "/api/confirm/start", {}, tok)
    assert sent[-1]["chat_id"] == 1


def test_email_when_second_factor_on(server, monkeypatch):
    p, base, sent = server
    mails = []
    monkeypatch.setattr(p.email, "wants_second", lambda uid: uid == 1)
    monkeypatch.setattr(p.people, "email", lambda uid: {"address": "owner@example.com", "second_factor": True})
    monkeypatch.setattr(p.email, "deliver", lambda to, subject, text, **kw: mails.append((to, text)))
    tok = p.auth.issue(1)
    code, d = call(base, "/api/confirm/start", {}, tok)
    assert code == 200 and d["via"] == "email" and "owner@example.com" not in d["to"] and sent == []
    good = re.search(r"(\d{6})", mails[-1][1]).group(1)
    assert mails[-1][0] == "owner@example.com"
    assert call(base, "/api/confirm/verify", {"id": d["id"], "code": good}, tok)[0] == 200
    assert call(base, "/api/run", RUN, tok)[0] == 200


def test_code_requests_limited_apart_from_login(server):
    p, base, _ = server
    tok = p.auth.issue(1)
    for _ in range(webauth.START_LIMIT[0]):
        assert call(base, "/api/confirm/start", {}, tok)[0] == 200
    code, d = call(base, "/api/confirm/start", {}, tok)
    assert code == 400 and "слишком много" in d["error"]
    p.auth.start()                                                              # вход кодом — свой счётчик


def test_code_pinned_where_to_look_and_unpinned(server, monkeypatch):
    """21.11: владелец не нашёл четыре дошедших кода — их утопило зеркало сессий в том же чате. Код закрепляется,
    экран говорит, когда и в какой чат он ушёл, и даёт ссылку на бота; после подтверждения закреп снимается.
    Код идёт прямым сообщением бота — каналы уведомлений (notify_channels.json) на него не влияют."""
    p, base, _ = server
    calls = []

    def api(method, **kw):
        calls.append((method, kw))
        if method == "sendMessage":
            if kw["chat_id"] == 3:
                from gas_pult.telegram import TelegramError
                raise TelegramError("sendMessage", "Bad Request: user not found")
            return {"message_id": 77}
        return {"username": "pult_bot", "first_name": "Пульт"} if method == "getMe" else {}
    monkeypatch.setattr(p.pult, "api", api)
    (p.cfg.data / "notify_channels.json").write_text(json.dumps({"1": {"telegram": False}}))
    tok = p.auth.issue(1)
    code, d = call(base, "/api/confirm/start", {}, tok)
    assert code == 200 and d["chat"] == "Пульт" and d["bot"] == "pult_bot" and abs(d["at"] - time.time()) < 5
    assert ("pinChatMessage", {"chat_id": 1, "message_id": 77, "disable_notification": True}) in calls
    good = code_in(next(kw["text"] for m, kw in calls if m == "sendMessage"))
    assert call(base, "/api/confirm/verify", {"id": d["id"], "code": good}, tok) == (200, {"ok": True})
    assert ("unpinChatMessage", {"chat_id": 1, "message_id": 77}) in calls
    # вход кодом владельца (LEGACY): владелец, не открывший бота, не мешает остальным
    p.cfg.owners = [1, 3]
    calls.clear()
    out = p.confirm_start(p.auth.issue(webauth.LEGACY), webauth.LEGACY, "", "")
    assert out["via"] == "telegram" and [kw["chat_id"] for m, kw in calls if m == "sendMessage"] == [1, 3]


def test_screen_shows_bot_link():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/js/confirm.js").read_text(encoding="utf-8")
    assert 'id="cfBot"' in html and "Открыть чат с ботом" in html and '"https://t.me/" + r.bot' in html
    assert "он закреплён сверху" in html


def test_tg_button_confirms_only_its_session_once(server, monkeypatch, tmp_path):
    """21.11: «чтобы код сразу подсказывался» — iOS берёт коды только из SMS; вместо цифр — кнопка
    «✅ Подтвердить вход» под кодом. Подтверждает только ту сессию, что запросила код; только тот Telegram; один раз."""
    p, base, _ = server
    calls = []
    monkeypatch.setattr(p.pult, "api", lambda method, **kw: calls.append((method, kw)) or
                        ({"message_id": 5} if method == "sendMessage" else {}))
    tok, other = p.auth.issue(1), p.auth.issue(1)
    code, d = call(base, "/api/confirm/start", {}, tok)
    assert code == 200
    kb = next(kw["reply_markup"] for m, kw in calls if m == "sendMessage")
    btn = kb["inline_keyboard"][0][0]
    assert btn["text"] == "✅ Подтвердить вход" and btn["callback_data"] == "cf:" + d["id"]
    assert call(base, "/api/confirm/check", {}, tok) == (200, {"ok": False})
    tc = webauth.TgConfirm(webauth.Auth(p.auth.store))                     # бот — другой процесс, свой объект
    assert not tc.approve(d["id"], 2, p.cfg.owners)                        # чужой Telegram — нет
    code, d = call(base, "/api/confirm/start", {}, tok)                    # (тот запрос сгорел) — новый
    assert tc.approve(d["id"], 1, p.cfg.owners)
    assert call(base, "/api/confirm/check", {}, tok) == (200, {"ok": True})
    assert call(base, "/api/run", RUN, tok)[0] == 200                       # команды — можно
    assert call(base, "/api/run", RUN, other)[0] == 403                     # другая сессия того же человека — нет
    assert not tc.approve(d["id"], 1, p.cfg.owners)                         # один раз
    assert (p.auth.store.with_name("web_confirm_tg.json").stat().st_mode & 0o777) == 0o600


def test_tg_button_expires(server):
    p, _, _ = server
    tok = p.auth.issue(1)
    tc = webauth.TgConfirm(p.auth)
    tc.offer("r1", tok, 1)
    d = json.loads(tc.store.read_text())
    d["r1"]["exp"] = time.time() - 1
    tc.store.write_text(json.dumps(d))
    assert not tc.approve("r1", 1, [1]) and p.auth.needs_confirm(tok)


def test_bot_button_handler_and_terminal_words():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src/gas_pult"
    bot = (root / "bot.py").read_text(encoding="utf-8")
    assert 'if kind == "cf":' in bot and "TgConfirm(Auth(" in bot
    assert bot.index('if kind == "cf":') < bot.index('if q["from"]["id"] not in self.cfg.owners and kind not in')
    tty = (root / "web/js/tty.js").read_text(encoding="utf-8")
    assert '? "Терминал" : d.name' in tty and "раньше tmux" not in tty
    html = (root / "web/index.html").read_text(encoding="utf-8")
    assert 'shell: "командная строка сервера"' in html and 'part("confirm")' in html
