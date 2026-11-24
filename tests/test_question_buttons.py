"""Вопрос Claude с вариантами — кнопками в чате (22.11, обзор интерфейса: 5 повторов «Claude ждёт ответа» за 36 с).

Образцы — настоящие экраны Claude Code 2.1 из tmux (tests/fixtures/cc_screens/, путь папки заменён): вопрос агента
(AskUserQuestion) с пояснениями между пунктами и чертой перед «Chat about this», два вопроса сразу (шапка ☐), сводка
«Review your answers» (без подсказки внизу) и доверие к папке (меню без номеров). Разбор — humanize.parse (его же
отдаёт /api/screen → карточка js/toolcard.js); нажатие — тот же /api/select (стрелки и Enter) или /api/key (Esc).
Текст, отправленный во время вопроса, в окно не уходит: сервер отвечает code=question, панель подсвечивает варианты и
оставляет текст в поле."""

import contextlib
import json
import threading
import types
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import access, bot, focus, humanize, webapp, webauth
from gas_pult.config import Config
from gas_pult.panel import sessions as panel_sessions

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "gas_pult" / "web"
CC = ROOT / "tests" / "fixtures" / "cc_screens"


def screen(name: str) -> list[str]:
    return (CC / f"{name}.txt").read_text(encoding="utf-8").splitlines()


# ---------- разбор вариантов на настоящих экранах ----------

def test_fixtures_have_no_personal_paths():
    for f in CC.glob("*.txt"):
        t = f.read_text(encoding="utf-8")
        assert not any(x in t for x in ("/tmp/claude", "-home-")), f.name


def test_question_with_descriptions_and_separator():
    a = humanize.parse(screen("question"), target=True)
    assert a["kind"] == "question" and a["title_ru"] == "Какой отчёт прислать утром?" and "target" not in a
    assert [(o["label_ru"], o["send"]) for o in a["options"]] == [
        ("Короткий", {"n": "1"}), ("Подробный", {"n": "2"}), ("Без отчёта", {"n": "3"}),
        ("Свой вариант", {"key": "Escape", "compose": True}),
        ("Обсудить с агентом", {"key": "Escape", "compose": True})]


def test_two_questions_tabs():
    a = humanize.parse(screen("question2"), target=True)
    assert a["kind"] == "question" and a["title_ru"] == "Формат?"
    assert [o["label_ru"] for o in a["options"]][:2] == ["PDF", "Word"]


def test_review_answers_without_footer():
    """Claude Code 2.1: сводка ответов — без «Enter to select»; раньше пульт её не узнавал и печатал текст в меню."""
    a = humanize.parse(screen("submit"))
    assert a["kind"] == "submit" and [(o["key"], o["send"]) for o in a["options"]] == [
        ("submit", {"n": "1"}), ("cancel", {"n": "2"})]
    assert humanize.DIALOG.search("\n".join(screen("submit")))


def test_trust_plain_menu():
    a = humanize.parse(screen("trust"))
    assert a["kind"] == "trust"
    assert {o["send"].get("text") for o in a["options"]} >= {"No, exit", "Yes, I trust this folder"}


@pytest.mark.parametrize("name", ["question", "question2", "submit", "trust"])
def test_bot_sees_question_on_real_screens(name):
    scr = "\n".join(screen(name)[-15:])                       # ready_for_text смотрит 15 строк снизу
    assert bot.QUESTION.search(scr) and not bot.free(scr)


# ---------- нажатие → нужная клавиша ----------

class MenuTmux:
    """Экран вопроса, на котором ❯ двигается стрелками, как в Claude Code; записывает нажатые клавиши."""
    def __init__(self, lines):
        self.lines, self.keys_sent = list(lines), []

    def screen(self, wid, n=60):
        return self.lines[-n:]

    def keys(self, wid, *keys):
        self.keys_sent += keys
        rows = [i for i, x in enumerate(self.lines) if humanize.OPT.match(x.strip())]
        cur = next(i for i in rows if x_sel(self.lines[i]))
        for k in keys:
            if k in ("Down", "Up"):
                j = rows.index(cur) + (1 if k == "Down" else -1)
                nxt = rows[max(0, min(len(rows) - 1, j))]
                self.lines[cur] = self.lines[cur].replace("❯", " ", 1)
                self.lines[nxt] = self.lines[nxt].replace("  ", "❯ ", 1)
                cur = nxt


def x_sel(line: str) -> bool:
    return line.lstrip().startswith("❯")


@pytest.mark.parametrize("n,keys", [("1", ["Enter"]), ("3", ["Down", "Down", "Enter"])])
def test_select_moves_with_arrows_and_enter(monkeypatch, n, keys):
    monkeypatch.setattr(panel_sessions.time, "sleep", lambda s: None)
    t = MenuTmux(screen("question"))
    me = types.SimpleNamespace(tmux=t, pult=types.SimpleNamespace(hold=lambda wid: contextlib.nullcontext()))
    webapp.Panel.select(me, {"id": "@1"}, "", n, True)
    assert t.keys_sent == keys                               # цифрой не выбираем — стрелки до пункта и Enter


# ---------- отправка во время вопроса: ничего не ушло в tmux, код question ----------

def test_ready_for_text_raises_awaits_choice_without_keys():
    sent = []
    p = bot.Pult.__new__(bot.Pult)
    p.tmux = types.SimpleNamespace(window=lambda wid: {"id": wid, "cmd": "claude"},
                                   screen=lambda wid, n=15: screen("question")[-n:],
                                   keys=lambda *a: sent.append(a), paste=lambda *a, **k: sent.append(a))
    with pytest.raises(bot.AwaitsChoice) as e:
        p.ready_for_text("@1")
    assert e.value.code == "question" and isinstance(e.value, bot.NotReady) and sent == []


class Wins:
    def __init__(self):
        self.w = {"@1": {"id": "@1", "name": "shop", "path": "/srv/shop", "cmd": "claude"}}

    def window(self, wid):
        return self.w.get(str(wid))

    def windows(self):
        return list(self.w.values())

    @contextlib.contextmanager
    def scope(self, slug):
        yield

    all_spaces = contextlib.nullcontext


@pytest.fixture
def server(monkeypatch):
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.accept(1)
    p.people.set_country(1, chosen="NL")
    wins = Wins()
    monkeypatch.setattr(p, "tmux", wins)
    monkeypatch.setattr(p, "window", lambda wid: wins.window(wid))
    monkeypatch.setattr(p, "sessions", lambda pool=None, who=None: [{"id": "@1", "name": "shop"}])
    monkeypatch.setattr(p, "check", lambda profile, uid: None)
    keys = []

    def to_claude(w, text):                                 # как настоящий: на экране вопрос — исключение до вставки
        raise bot.AwaitsChoice("Claude ждёт ответа на вопрос в этом окне — ответьте на экране (1 2 3 или Esc)")
    monkeypatch.setattr(p.pult, "to_claude", to_claude)
    monkeypatch.setattr(p, "key", lambda w, k: keys.append((w["id"], k)) or ["❯ "])
    monkeypatch.setattr(p, "select", lambda w, text, n="", go=True: keys.append((w["id"], "n" + n)) or ["❯ "])
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"p": p, "base": f"http://127.0.0.1:{srv.server_address[1]}", "tok": p.auth.issue(1), "keys": keys}
    srv.shutdown()


def call(base, path, body=None, cookie="", headers=None):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": cookie, **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read()), r.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), ""


def test_send_during_question_is_code_question(server):
    owner = f"{webauth.COOKIE}={server['tok']}"
    code, d, _ = call(server["base"], "/api/send", {"w": "@1", "text": "привет", "id": "m1"}, owner)
    assert code == 400 and d["code"] == "question" and "ждёт ответа" in d["error"]


def test_focus_link_can_answer_question(server):
    """Фокус-ссылка отвечает на вопрос теми же /api/key и /api/select — права не расширяли."""
    owner = f"{webauth.COOKIE}={server['tok']}"
    code, d, _ = call(server["base"], "/api/focus/new", {"w": "@1", "base": server["base"]}, owner)
    token = d["url"].split("#focus=")[1]
    _, _, setc = call(server["base"], "/api/focus/open", {"token": token, "privacy": True}, "", {focus.HEADER: "1"})
    fc, fx = setc.split(";")[0], {focus.HEADER: "1"}
    assert call(server["base"], "/api/select", {"w": "@1", "text": "", "n": "2", "go": True}, fc, fx)[0] == 200
    assert call(server["base"], "/api/key", {"w": "@1", "key": "Escape"}, fc, fx)[0] == 200
    assert server["keys"] == [("@1", "n2"), ("@1", "Escape")]
    code, d, _ = call(server["base"], "/api/send", {"w": "@1", "text": "x", "id": "m2"}, fc, fx)
    assert code == 400 and d["code"] == "question"
    assert {"/api/key", "/api/select"} <= access.FOCUS_POST and {"/api/key", "/api/select"} <= access.DEMO_POST


# ---------- панель: код на месте ----------

def test_panel_keeps_text_and_nudges():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    send = html[html.index("async function sendText()"):html.index("const msgId = ")]
    assert send.index("if (askWaits()) return askNudge();") < send.index("pending.push(p)")    # до очереди и до поля
    assert 'e.code === "question"' in html and "Выберите вариант выше" in html
    assert 'if (SIM.ask) return sNudge();' in html and 'data-act="bug"' in html and "data-bug" in html
    assert "body.focus:not(.split) #bugBtn" in html
    assert len(html.encode()) < 770000
    for lang in ("ru", "en"):
        d = json.loads((WEB / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        assert d["s.answer.wait"] and d["set.bug"]


# ---------- e2e: демо, 390 и 1366 ----------

VIS = ("(s) => { const e = document.querySelector(s); "
       "return !!e && e.offsetParent !== null && getComputedStyle(e).display !== 'none'; }")
SPY = ("() => { window.__sent = []; const f = window.demoApi; "
       "window.demoApi = (p, b) => { if (p === '/api/send') __sent.push(b); return f(p, b); }; }")


@pytest.fixture
def web():
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&noscroll"
    srv.shutdown()


def test_e2e_question_buttons(web):
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        br = p.chromium.launch()
        for w, h in ((390, 844), (1366, 860)):
            for q in ("open=@2&ask=question", "focus&ask=question", "tester&open=t:demo:@1&ask=question"):
                pg = br.new_page(viewport={"width": w, "height": h})
                errs = []
                pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
                pg.goto(f"{web}&{q}")
                pg.wait_for_selector(".ask.cc", timeout=10000)
                assert "Короткий — три цифры" in pg.inner_text(".ask.cc") and pg.locator(".ask.cc .cc-esc").count() == 1
                pg.wait_for_function("() => !!window.demoApi")
                pg.evaluate(SPY)
                pg.fill("#input", "мой текст во время вопроса")
                pg.click("#send")
                pg.wait_for_selector("#askTip:not([hidden])")
                assert "Выберите вариант выше" in pg.inner_text("#askTip")
                assert pg.input_value("#input") == "мой текст во время вопроса"          # текст остался в поле
                assert pg.evaluate("__sent.length") == 0 and pg.locator(".ask.cc.nudge").count() == 1
                pg.click(".ask.cc .opt[data-tc='1']")                                  # одно нажатие — выбор
                pg.wait_for_function("!document.querySelector('.ask.cc')", timeout=10000)
                assert pg.input_value("#input") == "мой текст во время вопроса"
                assert not errs, (w, q, errs)
                pg.close()
        pg = br.new_page(viewport={"width": 390, "height": 844})                        # «Отмена» — Esc
        pg.goto(f"{web}&open=@2&ask=question")
        pg.click(".ask.cc .cc-esc")
        pg.wait_for_function("!document.querySelector('.ask.cc')", timeout=10000)
        br.close()


def test_e2e_bug_button_does_not_squeeze_name(web):
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": 390, "height": 844})                          # фокус на телефоне
        pg.goto(f"{web}&focus")
        pg.wait_for_selector("#target")
        pg.wait_for_timeout(800)
        assert not pg.evaluate(VIS, "#bugBtn") and pg.evaluate(VIS, "#menuBtn")
        assert pg.evaluate("document.getElementById('target').clientWidth") >= 100     # до #461 — 110, с жуком — 68
        pg.click("#menuBtn")
        pg.click("#menu [data-act=bug]")
        pg.wait_for_selector("#bugTitle")
        pg.close()
        pg = br.new_page(viewport={"width": 1366, "height": 860})                         # широкий — жук в строке
        pg.goto(f"{web}&focus")
        pg.wait_for_selector("#target")
        pg.wait_for_timeout(800)
        assert pg.evaluate(VIS, "#bugBtn")
        assert pg.evaluate("(() => { const t = document.getElementById('target'); "
                           "return t.scrollWidth <= t.clientWidth; })()")
        pg.close()
        pg = br.new_page(viewport={"width": 390, "height": 844})                          # простой режим — в настройках
        pg.goto(f"{web}&simple=1&ask=question")
        pg.wait_for_selector("#sAsk .s-ask")
        pg.fill("#sInput", "текст")
        pg.click("#sSend")
        pg.wait_for_selector(".s-ask .s-nudge")
        assert pg.input_value("#sInput") == "текст"
        pg.click("#sSet")
        pg.click("[data-bug]")
        pg.wait_for_selector("#bugTitle")
        br.close()
