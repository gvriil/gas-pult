"""Живой терминал в панели (задача 50): клавиши и текст прямо в окно, вся история tmux страницами, маскировка
секретов; кому можно — только режим разработчика. Без живого tmux: окна и команды tmux подменены."""

import contextlib
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import focus, spaces, termwin, webapp, webauth
from gas_pult.config import Config

# заведомо поддельный токен, склеен из частей — не похож на настоящий для сканеров
FAKE_TOKEN = "gh" + "p_" + "Z" * 36


class FakeTm:
    """Сервер tmux: окно из ``rows`` строк истории + экран ``height``; запоминает вызовы и stdin."""

    def __init__(self, rows=1200, height=40, alive=("@1", "@2", "@3", "@9")):
        self.rows, self.height, self.alive, self.calls = rows, height, set(alive), []

    def run(self, *args, input=None):
        self.calls.append((args, input))
        if args[0] == "display-message":
            if args[args.index("-t") + 1] not in self.alive:
                return ""
            return f"{self.rows}\t50000\t{self.height}\t\t0\t0\n"
        if args[0] == "capture-pane":
            s, e = int(args[args.index("-S") + 1]), int(args[args.index("-E") + 1])
            return "".join(f"строка {y + self.rows}" + (f" {FAKE_TOKEN}" if y + self.rows == 7 else "") + "\n"
                           for y in range(s, e + 1))
        return ""


def test_type_goes_through_buffer_not_argv():
    tm = FakeTm()
    termwin.tty_type(tm, "@1", "секрет s3cret")
    args = [a for a, _ in tm.calls]
    assert args[0][:3] == ("load-buffer", "-b", args[0][2]) and tm.calls[0][1] == "секрет s3cret"   # через stdin
    assert all("s3cret" not in " ".join(a) for a in args)                      # не в аргументах команд
    paste = next(a for a in args if a[0] == "paste-buffer")
    assert "-d" in paste and "-p" not in paste and paste[-1] == "@1"           # буфер удаляется сразу
    assert args[-1][0] == "delete-buffer"
    tm.calls.clear()
    termwin.tty_type(tm, "@1", "строка 1\r\nстрока 2\x1b[31m\x07")
    assert tm.calls[0][1] == "строка 1\nстрока 2[31m"                          # управляющие знаки — вон
    assert "-p" in next(a for a, _ in tm.calls if a[0] == "paste-buffer")      # многострочное — в скобках
    for bad in ("", "\x1b", "x" * (termwin.TEXT_MAX + 1)):
        with pytest.raises(ValueError):
            termwin.tty_type(tm, "@1", bad)


def test_keys_whitelist():
    tm = FakeTm()
    for k in ("Up", "Down", "Left", "Right", "Escape", "Tab", "Enter", "BSpace", "PPage", "NPage", "Home", "End",
              "C-c", "C-d", "C-l", "C-r"):
        termwin.tty_key(tm, "@1", k, owner=False)
        assert tm.calls[-1][0] == ("send-keys", "-t", "@1", k)
    termwin.tty_key(tm, "@1", "C-z", owner=True)
    for bad in ("C-z", "rm -rf", "-l", "Enter; ls", "C-c C-c"):
        with pytest.raises(ValueError):
            termwin.tty_key(tm, "@1", bad, owner=False)                       # Ctrl+Z — только владельцу


def test_history_pages_and_masks():
    tm = FakeTm(rows=1200, height=40)
    d = termwin.history(tm, "@1")                                             # хвост: последние PAGE строк
    assert d["alive"] and d["total"] == 1240 and d["end"] == 1240 and d["start"] == 1240 - termwin.PAGE
    assert d["lines"][0] == f"строка {d['start']}" and d["lines"][-1] == "строка 1239"
    caps = [a for a, _ in tm.calls if a[0] == "capture-pane"]               # история и экран — отдельно
    assert all("-J" in a for a in caps) and [(a[a.index("-S") + 1], a[a.index("-E") + 1]) for a in caps] == \
        [(str(d["start"] - 1200), "-1"), ("0", "39")]
    assert d["cut"] == 1200 - d["start"] and d["lines"][d["cut"]] == "строка 1200"   # выше cut — уже не меняется
    up = termwin.history(tm, "@1", end=d["start"])                            # страница выше
    assert up["end"] == d["start"] and up["start"] == d["start"] - termwin.PAGE
    top = termwin.history(tm, "@1", end=200)
    assert top["start"] == 0 and len(top["lines"]) == 200 and top["cut"] == 200
    above = termwin.history(tm, "@1", end=600, everything=True)               # поиск: всё выше загруженного
    assert (above["start"], above["end"], len(above["lines"])) == (0, 600, 600)
    assert FAKE_TOKEN not in "\n".join(top["lines"]) and "скрыт" in top["lines"][7]   # секреты замаскированы
    tail = termwin.history(tm, "@1", start=1000)                              # живой хвост после прокрутки вверх
    assert (tail["start"], tail["end"], tail["cut"]) == (1000, 1240, 200)
    everything = termwin.history(tm, "@1", everything=True)
    assert everything["start"] == 0 and len(everything["lines"]) == 1240
    big = FakeTm(rows=termwin.MAX_ROWS + 5000)
    d = termwin.history(big, "@1", everything=True)                           # глубже MAX_ROWS — не отдаём
    assert d["floor"] == d["start"] == 5040 and len(d["lines"]) == termwin.MAX_ROWS
    assert termwin.history(big, "@1", end=0)["start"] == 5040
    assert termwin.history(FakeTm(alive=()), "@1") == {"alive": False, "lines": [], "start": 0, "end": 0, "total": 0}


def test_space_window_goes_to_its_tmux():
    owner, space = FakeTm(), FakeTm()
    r = spaces.Routed(owner, space_of=lambda s: spaces.Space(s, space), slugs=lambda: ["demo"])
    termwin.tty_type(r, "t:demo:@3", "привет")
    termwin.tty_key(r, "t:demo:@3", "Enter")
    termwin.history(r, "t:demo:@3")
    assert owner.calls == []                                                  # tmux владельца не трогали
    assert {a[a.index("-t") + 1] for a, _ in space.calls if "-t" in a} == {"@3"}
    assert next(a for a, _ in space.calls if a[0] == "load-buffer") and space.calls[0][1] == "привет"
    with r.scope("other"), pytest.raises(LookupError):
        termwin.tty_key(r, "t:demo:@3", "Enter")                              # чужое пространство — «окна нет»


# ---------- панель: кому можно ----------
WINS = {"@1": {"id": "@1", "name": "работа", "cmd": "claude", "mark": "claude", "path": "/tmp/w", "stopped": False},
        "@2": {"id": "@2", "name": "стоп", "cmd": "bash", "mark": "claude", "path": "/tmp/w", "stopped": True},
        "@3": {"id": "@3", "name": "чужое", "cmd": "bash", "mark": "", "path": "/tmp/w", "stopped": False},
        "@9": {"id": "@9", "name": termwin.WINDOW, "cmd": "bash", "mark": "", "path": "/tmp/w", "stopped": False},
        "t:demo:@1": {"id": "t:demo:@1", "name": "сверка", "cmd": "claude", "mark": "claude", "path": "/tmp/d",
                      "space": "demo", "stopped": False}}


class Wins(FakeTm):
    session = "main"

    def __init__(self):
        super().__init__(rows=100, height=20, alive=set(WINS))

    def window(self, wid):
        return WINS.get(str(wid))

    def windows(self):
        return list(WINS.values())

    @contextlib.contextmanager
    def scope(self, slug):
        yield

    all_spaces = contextlib.nullcontext


@pytest.fixture
def server(monkeypatch):
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.add(2, "member", "Иван")
    p.people.add(3, "viewer", "Анна")
    p.people.add(4, "member", "Олег")
    p.people.set_ui(4, {"persona": "business_owner", "onboarded": True})     # простой режим
    for uid in (1, 2, 3, 4):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    wins = Wins()
    monkeypatch.setattr(p, "tmux", wins)
    monkeypatch.setattr(p, "window", lambda wid: WINS.get(wid) if WINS.get(wid, {}).get("cmd") == "claude" else None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield p, f"http://127.0.0.1:{srv.server_address[1]}", wins
    srv.shutdown()


def confirmed(p, uid):
    """Сессия, уже подтверждённая кодом (test_confirm_code.py): эти тесты — про терминал, не про подтверждение."""
    t = p.auth.issue(uid)
    rid, code = p.auth.confirm_start(t)
    p.auth.confirm_verify(t, rid, code)
    return t


def call(base, path, body=None, tok="", headers=None):
    h = {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={tok}" if tok else "", **(headers or {})}
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, h)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_owner_reads_types_and_keys_everywhere(server):
    p, base, wins = server
    tok = confirmed(p, 1)
    assert call(base, "/api/meta", tok=tok)[1]["tty"] is True
    code, d = call(base, "/api/tty?w=%401", tok=tok)
    assert code == 200 and d["kind"] == "session" and d["total"] == 120 and d["lines"][-1] == "строка 119"
    code, d = call(base, "/api/tty?w=%401&end=50", tok=tok)
    assert code == 200 and (d["start"], d["end"]) == (0, 50)
    for wid in ("@1", "@2", "@3", "@9", "t:demo:@1"):        # своё, остановленное, чужое, gp-term, пространство
        assert call(base, "/api/tty/type", {"w": wid, "text": "ls"}, tok)[0] == 200, wid
        assert call(base, "/api/tty/key", {"w": wid, "key": "C-z"}, tok)[0] == 200, wid
    assert call(base, "/api/tty?w=%409", tok=tok)[1]["kind"] == "term"
    assert call(base, "/api/tty/key", {"w": "@1", "key": "rm"}, tok)[0] == 400
    assert call(base, "/api/tty/type", {"w": "@7", "text": "x"}, tok)[0] == 404
    assert all("ls" not in " ".join(a) for a, _ in wins.calls if a[0] != "load-buffer")


def test_member_only_running_sessions(server):
    p, base, _ = server
    tok = confirmed(p, 2)
    assert call(base, "/api/meta", tok=tok)[1]["tty"] is True                  # вид разработчика по умолчанию
    assert call(base, "/api/tty?w=%401", tok=tok)[0] == 200
    assert call(base, "/api/tty/type", {"w": "@1", "text": "привет"}, tok)[0] == 200
    assert call(base, "/api/tty/key", {"w": "@1", "key": "C-c"}, tok)[0] == 200
    assert call(base, "/api/tty/key", {"w": "@1", "key": "C-z"}, tok)[0] == 400       # в фон — только владельцу
    assert call(base, "/api/tty?w=%402", tok=tok)[0] == 200                           # остановленную — смотреть
    code, d = call(base, "/api/tty/type", {"w": "@2", "text": "ls"}, tok)            # но не писать в командную строку
    assert code == 400 and "остановлен" in d["error"]
    assert call(base, "/api/tty/key", {"w": "@2", "key": "Enter"}, tok)[0] == 400
    for wid in ("@3", "@9", "t:demo:@1"):                                     # не сессия, gp-term, пространство
        assert call(base, "/api/tty?w=" + wid.replace("@", "%40"), tok=tok)[0] == 400, wid
        assert call(base, "/api/tty/type", {"w": wid, "text": "x"}, tok)[0] == 400, wid


def test_not_for_simple_viewer_tester(server):
    p, base, _ = server
    for uid in (3, 4):                                                        # наблюдатель, простой режим
        tok = p.auth.issue(uid)
        assert call(base, "/api/meta", tok=tok)[1]["tty"] is False
        assert call(base, "/api/tty?w=%401", tok=tok)[0] == 403, uid
        assert call(base, "/api/tty/type", {"w": "@1", "text": "x"}, tok)[0] == 403, uid
        assert call(base, "/api/tty/key", {"w": "@1", "key": "Enter"}, tok)[0] == 403, uid
    p.people.set_ui(2, {"persona": "developer", "onboarded": True, "hidden": ["cap.dev_terminal"]})
    assert call(base, "/api/tty?w=%401", tok=p.auth.issue(2))[0] == 403          # «Экран терминала» скрыт
    for path in webapp.TTY:
        assert path not in webapp.SPACE_OK and path not in webapp.FOCUS_GET | webapp.FOCUS_POST
        assert path in webapp.MEMBER_ONLY


def test_not_in_focus(server):
    p, base, _ = server
    link = p.focus.new(WINS["@1"], 1)
    value, _ = p.focus.open(link["token"], "")
    fx = {focus.HEADER: "1", "Cookie": f"{focus.COOKIE}={value}"}
    code, d = call(base, "/api/tty?w=%401", headers=fx)
    assert code == 403 and d["code"] == "focus_scope"
    assert call(base, "/api/tty/key", {"w": "@1", "key": "Enter"}, headers=fx)[0] == 403
    code, d = call(base, "/api/tty?w=%401", headers={"Cookie": f"{focus.COOKIE}={value}"})   # без заголовка — тоже
    assert code == 403


def test_password_window_not_typed_from_telegram(server, monkeypatch):
    _p, base, _ = server
    monkeypatch.setattr(webapp, "verify", lambda init, token, now=None: {"id": 1, "first_name": "Владелец"})
    tg = {"X-Telegram-Init-Data": "query_id=1"}
    code, d = call(base, "/api/tty/type", {"w": "@9", "text": "x"}, headers=tg)
    assert code == 400 and "Telegram" in d["error"]
    assert call(base, "/api/tty/type", {"w": "@1", "text": "x"}, headers=tg)[0] == 200   # в сессию — можно
    assert call(base, "/api/tty/key", {"w": "@9", "key": "C-c"}, headers=tg)[0] == 200


def test_e2e_live_terminal_in_browser():
    import importlib.util
    import shutil
    from functools import partial
    from http.server import SimpleHTTPRequestHandler
    from pathlib import Path

    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    root = Path(__file__).resolve().parents[1]
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler,
                                                        directory=str(root / "src" / "gas_pult" / "web")))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    spec = importlib.util.spec_from_file_location("tty_demo", root / "tests" / "e2e" / "tty_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
