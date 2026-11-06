"""pass / GPG на сервере пульта (задача 40): проверить заранее, не запускать при заблокированном, разблокировать окном
pass-unlock (пароль — не через Telegram), «разблокирован до …», одно сообщение после перезагрузки."""

import json
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from gas_pult import bot, commands, passcheck, webapp, webauth
from gas_pult.config import Config


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = tmp_path / "store"
    (s / "infra").mkdir(parents=True)
    (s / "infra" / "x.gpg").write_bytes(b"gpg")
    monkeypatch.setenv("PASSWORD_STORE_DIR", str(s))
    monkeypatch.setattr(passcheck.shutil, "which", lambda name: "/usr/bin/" + name if name == "gpg" else None)
    passcheck._cache.clear()
    return s


def runner_rc(rc, calls=None):
    def run(argv, **kw):
        if calls is not None:
            calls.append(argv)
        return subprocess.CompletedProcess(argv, rc)
    return run


def test_needs():
    for cmd in ("pass show infra/x", "cd ~ && pass show a", "cat f | gpg -d", "gpg2 --decrypt f", "(pass ls)"):
        assert passcheck.needs(cmd), cmd
    for cmd in ("passwd", "bypass x", "compass", "ls gpgfiles", "git push"):
        assert not passcheck.needs(cmd), cmd


def test_unlocked_checks_like_pass_unlock(store):
    calls = []
    assert passcheck.unlocked(fresh=True, runner=runner_rc(0, calls)) is True
    assert calls[0][:5] == ["gpg", "--batch", "--pinentry-mode", "error", "-q"] and calls[0][-1].endswith(".gpg")
    assert passcheck.unlocked(runner=runner_rc(2)) is True                     # кэш минуту
    assert passcheck.unlocked(fresh=True, runner=runner_rc(2)) is False


def test_no_store_is_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("PASSWORD_STORE_DIR", str(tmp_path / "none"))
    passcheck._cache.clear()
    assert passcheck.unlocked(fresh=True, runner=runner_rc(0)) is None
    assert passcheck.status({}, fresh=True, runner=runner_rc(0))["state"] == "absent"


def test_ttl(tmp_path):
    c = tmp_path / "gpg-agent.conf"
    c.write_text("# x\ndefault-cache-ttl 2592000\nmax-cache-ttl 2592000\nallow-loopback-pinentry\n")
    assert passcheck.ttl(c) == 2592000
    assert passcheck.ttl(tmp_path / "none.conf") == passcheck.DEFAULT_TTL


def test_status_until_and_reboot(store, monkeypatch, tmp_path):
    st = {}
    monkeypatch.setattr(passcheck, "ttl", lambda conf=None: 30 * 86400)
    monkeypatch.setattr(passcheck, "boot_id", lambda: "boot-1")
    d = passcheck.status(st, lambda **kw: st.update(kw), fresh=True, runner=runner_rc(0), now=1000.0)
    assert d == {"state": "unlocked", "until": 1000 + 30 * 86400, "script": bool(passcheck.script())}
    assert st == {"pass_at": 1000.0, "pass_boot": "boot-1"}
    d = passcheck.status(st, lambda **kw: st.update(kw), fresh=True, runner=runner_rc(0), now=5000.0)
    assert d["until"] == 1000 + 30 * 86400                                   # время разблокировки — то, первое
    monkeypatch.setattr(passcheck, "boot_id", lambda: "boot-2")              # перезагрузка: заново
    d = passcheck.status(st, lambda **kw: st.update(kw), fresh=True, runner=runner_rc(2), now=9000.0)
    assert d["state"] == "locked" and d["until"] is None and st["pass_at"] is None


class FakeTmux:
    session = "main"

    def __init__(self, windows=()):
        self.ws, self.calls = list(windows), []

    def windows(self):
        return self.ws

    def window(self, wid):
        return next((w for w in self.ws if w["id"] == wid), None)

    def run(self, *args, input=None):
        self.calls.append((args, input))
        if args[0] == "new-window":
            self.ws.append({"id": "@9", "name": args[args.index("-n") + 1]})
            return "@9\n"
        return ""


def test_open_window_and_type_password_safely(monkeypatch, tmp_path):
    monkeypatch.setattr(passcheck, "script", lambda: None)
    with pytest.raises(ValueError, match="pass-unlock"):
        passcheck.open_window(FakeTmux())
    monkeypatch.setattr(passcheck, "script", lambda: "/home/u/.local/bin/pass-unlock")
    tm = FakeTmux([{"id": "@1", "name": "работа"}])
    assert passcheck.open_window(tm) == "@9" and "pass-unlock" in tm.calls[0][0][-1]
    assert passcheck.open_window(tm) == "@9" and len(tm.calls) == 1          # уже открыто — то же окно
    passcheck.type_password(tm, "@9", "s3cret пароль")
    args = [a for a, _ in tm.calls[1:]]
    assert ("load-buffer" in args[0]) and tm.calls[1][1] == "s3cret пароль"    # пароль — через stdin
    assert all("s3cret пароль" not in " ".join(a) for a in args)              # не в аргументах команд
    assert any(a[0] == "paste-buffer" and "-d" in a for a in args) and args[-1][-1] == "Enter"
    with pytest.raises(LookupError):
        passcheck.type_password(tm, "@1", "x")                                # только в окно pass-unlock
    with pytest.raises(ValueError):
        passcheck.type_password(tm, "@9", "две\nстроки")


# ---------- «Выполнить»: в боте и в панели ----------
def test_bot_run_does_not_start_when_locked(tmp_path, monkeypatch):
    c = commands.Commands("srv", tmp_path / "cmds.json", [], [])
    cid = "c1"
    c._save({cid: {"cmd": "pass show infra/x", "cwd": "/tmp", "win": "w", "ts": 0}})
    ran, sent = [], []
    monkeypatch.setattr(commands, "execute", lambda cmd, cwd: ran.append(cmd) or (0, 0.1, "ok"))
    c.guard = lambda cmd: "заблокировано" if passcheck.needs(cmd) else ""
    c.run(cid, False, lambda text, **kw: sent.append((text, kw)), lambda rows: {"rows": rows})
    assert ran == [] and sent[0][0] == "заблокировано" and sent[0][1]["reply_markup"]["rows"][0][0][1] == "pu:"
    c.guard = lambda cmd: ""
    c.run(cid, False, lambda text, **kw: sent.append((text, kw)), lambda rows: {"rows": rows})
    assert ran == ["pass show infra/x"]


def test_reboot_message_once(monkeypatch):
    st, sent = {}, []
    f = SimpleNamespace(state=lambda: dict(st), set_state=lambda **kw: st.update(kw),
                        broadcast=lambda text, **kw: sent.append((text, kw)))
    monkeypatch.setattr(passcheck, "boot_id", lambda: "boot-1")
    monkeypatch.setattr(passcheck, "unlocked", lambda fresh=False, runner=None: False)
    bot.Pult.boot_check(f)
    bot.Pult.boot_check(f)                                                     # та же загрузка — молчим
    assert len(sent) == 1 and "перезагрузился" in sent[0][0]
    assert sent[0][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "pu:"
    assert "пароль" in sent[0][0] and "не в Telegram" in sent[0][0]
    monkeypatch.setattr(passcheck, "boot_id", lambda: "boot-2")
    monkeypatch.setattr(passcheck, "unlocked", lambda fresh=False, runner=None: True)
    bot.Pult.boot_check(f)                                                     # разблокировано — не пишем
    assert len(sent) == 1 and st["boot_id"] == "boot-2"


@pytest.fixture
def server(monkeypatch, tmp_path):
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.accept(1)
    p.people.set_country(1, chosen="NL")
    cmds = [{"i": 0, "cmd": "pass show infra/x", "kind": "local", "danger": False, "sha": "aaa"}]
    monkeypatch.setattr(p, "commands", lambda w: cmds)
    monkeypatch.setattr(p, "window", lambda wid: {"id": wid, "path": "/tmp", "cmd": "claude", "name": "a"})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield p, f"http://127.0.0.1:{srv.server_address[1]}", p.auth.issue(1)
    srv.shutdown()


def call(base, path, body=None, tok="", headers=None):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={tok}",
                                  **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_panel_run_locked_and_password_not_from_telegram(server, monkeypatch):
    _p, base, tok = server
    ran = []
    monkeypatch.setattr(webapp, "execute", lambda cmd, cwd: ran.append(cmd) or (0, 0.1, "ok"))
    monkeypatch.setattr(passcheck, "unlocked", lambda fresh=False, runner=None: False)
    code, d = call(base, "/api/run", {"w": "@1", "i": 0, "sha": "aaa"}, tok)
    assert code == 200 and d["locked"] and "заблокировано" in d["error"] and ran == []
    monkeypatch.setattr(passcheck, "unlocked", lambda fresh=False, runner=None: True)
    code, d = call(base, "/api/run", {"w": "@1", "i": 0, "sha": "aaa"}, tok)
    assert code == 200 and d["code"] == 0 and ran == ["pass show infra/x"]
    # из Mini App (подписанный Telegram запрос владельца) пароль не принимаем — только браузер или терминал
    monkeypatch.setattr(webapp, "verify", lambda init, token, now=None: {"id": 1, "first_name": "Владелец"})
    typed = []
    monkeypatch.setattr(passcheck, "type_password", lambda tm, wid, text: typed.append(text))
    code, d = call(base, "/api/pass/type", {"w": "@9", "text": "x"}, "", {"X-Telegram-Init-Data": "query_id=1"})
    assert code == 400 and "Telegram" in d["error"] and typed == []
    code, d = call(base, "/api/pass/type", {"w": "@9", "text": "x"}, tok)          # браузер — можно
    assert code == 200 and typed == ["x"]
    assert "/api/pass/type" in webapp.OWNER_ONLY and "/api/pass" in webapp.OWNER_ONLY
