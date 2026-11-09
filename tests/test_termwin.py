"""Команде нужен ввод (задача 47): распознаватель, окно терминала панели вместо «▶️ Выполнить» (бот и панель),
пароль — только в браузере; кода pass/GPG (задача 40) больше нет."""

import importlib.util
import json
import re
import shutil
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from gas_pult import bot, commands, termwin, webapp, webauth
from gas_pult.config import SUDO_ALLOW, Config

ROOT = Path(__file__).resolve().parents[1]


# ---------- распознаватель ----------
@pytest.mark.parametrize("cmd", [
    "keepassxc-cli show db.kdbx Сервисы/почта",
    "/usr/bin/keepassxc-cli ls ~/vault/db.kdbx",
    "sudo -u svc keepassxc-cli ls db.kdbx",
    "env LANG=C keepassxc-cli ls db.kdbx",
    "TOKEN=$(keepassxc-cli show -a password db.kdbx x) && echo ok",
    "keepassxc.cli ls db.kdbx",                                   # snap
    "cd /srv && keepassxc-cli export db.kdbx > /dev/null",
])
def test_keepassxc_needs_input(cmd):
    assert termwin.needs_input(cmd), cmd


@pytest.mark.parametrize("cmd", [
    "sudo apt update", "sudo -u bob ls /root", "time sudo ls", "cd x && sudo -v", "doas reboot",
    "ssh host uptime", "scp f host:", "ssh-add ~/.ssh/id_ed25519", "ssh-keygen -t ed25519", "passwd", "su - root",
    "gpg -d f.gpg", "read -rsp 'Токен: ' T", "read -p 'Да? ' A",
    "echo 'Введите пароль и нажмите Enter'", "# спросит мастер-пароль\nmytool unlock",
])
def test_password_prompts_need_input(cmd):
    assert termwin.needs_input(cmd), cmd


@pytest.mark.parametrize("cmd", [
    "ls -la", "git push origin main", "npm test", "grep -r password config.toml", "cat ~/.config/svc/token",
    "echo hi | sudo -n tee /tmp/x", "sudo -n systemctl restart nginx", "sudo -u bob -n ls",
    "while read line; do echo $line; done < f", "sshd -t", "compass", "bypass x", "docker compose up -d",
    "export PASSWORD_FILE=~/.config/svc/pw", "systemctl --user restart gas-pult-webapp", "chmod 600 ~/.config/svc/env",
])
def test_ordinary_commands_not_touched(cmd):
    assert not termwin.needs_input(cmd), cmd


def test_allowed_sudo_runs_with_button(tmp_path):
    c = commands.Commands("box", tmp_path / "cmds.json", SUDO_ALLOW, [])
    assert c.kind("sudo apt install -y jq") == "local"             # разрешён без пароля — пульт добавит -n
    assert c.kind("sudo rm -rf /tmp/x") == "tty"
    assert c.kind("sudo -n rm -rf /tmp/x") == "sudo"
    assert c.kind("keepassxc-cli ls db.kdbx") == "tty"
    assert c.kind("ls") == "local"


# ---------- окно терминала ----------
class FakeTmux:
    session = "main"

    def __init__(self, windows=()):
        self.ws, self.calls = list(windows), []

    def windows(self):
        return self.ws

    def window(self, wid):
        return next((w for w in self.ws if w["id"] == wid), None)

    def screen(self, wid, n=25):
        return ["Пароль:"]

    def run(self, *args, input=None):
        self.calls.append((args, input))
        if args[0] == "new-window":
            self.ws.append({"id": "@9", "name": args[args.index("-n") + 1]})
            return "@9\n"
        return ""


def test_open_window_runs_command_in_folder(tmp_path):
    tm = FakeTmux()
    assert termwin.open_window(tm, "keepassxc-cli ls 'db.kdbx'", str(tmp_path)) == "@9"
    args = tm.calls[0][0]
    assert args[args.index("-n") + 1] == termwin.WINDOW and args[args.index("-c") + 1] == str(tmp_path)
    assert args[-1].startswith("bash -l -c ") and "keepassxc-cli ls" in args[-1] and "read -r _" in args[-1]
    assert termwin.screen(tm, "@9") == {"lines": ["Пароль:"], "alive": True}
    assert termwin.screen(tm, "@1") == {"lines": [], "alive": False}
    with pytest.raises(ValueError):
        termwin.open_window(tm, "  ", None)


def test_type_line_only_into_terminal_and_not_in_argv():
    tm = FakeTmux([{"id": "@1", "name": "работа"}, {"id": "@9", "name": termwin.WINDOW}])
    termwin.type_line(tm, "@9", "s3cret пароль")
    args = [a for a, _ in tm.calls]
    assert args[0][0] == "load-buffer" and tm.calls[0][1] == "s3cret пароль"   # пароль — через stdin
    assert all("s3cret пароль" not in " ".join(a) for a in args)               # не в аргументах команд
    assert any(a[0] == "paste-buffer" and "-d" in a for a in args) and args[-1][-1] == "Enter"
    with pytest.raises(LookupError):
        termwin.type_line(tm, "@1", "x")                                       # только в окно gp-term
    with pytest.raises(ValueError):
        termwin.type_line(tm, "@9", "две\nстроки")
    with pytest.raises(ValueError):
        termwin.key(tm, "@9", "rm")                                            # клавиши — только из списка
    termwin.key(tm, "@9", "C-c")
    termwin.close(tm, "@9")
    assert tm.calls[-1][0][:1] == ("kill-window",)


# ---------- бот: «⌨️ Открыть в терминале» вместо «▶️ Выполнить» ----------
def test_bot_offers_terminal_not_run(tmp_path, monkeypatch):
    c, sent, ran = commands.Commands("srv", tmp_path / "cmds.json", [], []), [], []
    monkeypatch.setattr(commands, "execute", lambda cmd, cwd: ran.append(cmd) or (0, 0.1, "ok"))
    send = lambda text, **kw: sent.append((text, kw))  # noqa: E731
    c.offer({"name": "w", "path": str(tmp_path)}, "```bash\nkeepassxc-cli show db.kdbx x\n```", send, lambda r: r)
    text, kw = sent[-1]
    assert "нужен ввод" in text and kw["reply_markup"][0][0][1].startswith("tw:")
    cid = kw["reply_markup"][0][0][1].split(":")[1]
    c.run(cid, True, send, lambda r: r)                                       # старая кнопка/«runok» — всё равно нет
    assert ran == [] and sent[-1][1]["reply_markup"][0][0][1] == f"tw:{cid}"


def test_bot_term_open(tmp_path, monkeypatch):
    c = commands.Commands("srv", tmp_path / "cmds.json", [], [])
    c._save({"a": {"cmd": "sudo apt update", "cwd": str(tmp_path), "win": "w", "ts": 0, "tty": True},
             "d": {"cmd": "sudo rm -rf /tmp/x", "cwd": str(tmp_path), "win": "w", "ts": 0, "tty": True}})
    sent, opened = [], []
    f = SimpleNamespace(cmds=c, tmux=FakeTmux(), send=lambda chat, text, **kw: sent.append((text, kw)),
                        panel_url=lambda view="": "https://panel.example/")
    monkeypatch.setattr(termwin, "open_window", lambda tm, cmd, cwd: opened.append((cmd, cwd)) or "@9")
    bot.Pult.term_open(f, 1, "a", False)
    assert opened == [("sudo apt update", str(tmp_path))]
    assert "не присылайте" in sent[-1][0]
    assert sent[-1][1]["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://panel.example/?term=%409"
    bot.Pult.term_open(f, 1, "d", False)                                      # опасная — сначала подтверждение
    assert len(opened) == 1 and sent[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "twok:d"
    bot.Pult.term_open(f, 1, "d", True)
    assert opened[-1][0] == "sudo rm -rf /tmp/x"


# ---------- панель ----------
@pytest.fixture
def server(monkeypatch, tmp_path):
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.accept(1)
    p.people.set_country(1, chosen="NL")
    cmds = [{"i": 0, "cmd": "keepassxc-cli ls db.kdbx", "kind": "tty", "danger": False, "sha": "aaa"},
            {"i": 1, "cmd": "brew install x", "kind": "foreign", "danger": False, "sha": "bbb"}]
    monkeypatch.setattr(p, "commands", lambda w: cmds)
    monkeypatch.setattr(p, "window", lambda wid: {"id": wid, "path": str(tmp_path), "cmd": "claude", "name": "a"})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    tok = p.auth.issue(1)
    rid, code = p.auth.confirm_start(tok)          # сессия подтверждена кодом (test_confirm_code.py)
    p.auth.confirm_verify(tok, rid, code)
    yield p, f"http://127.0.0.1:{srv.server_address[1]}", tok
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


def test_panel_run_refuses_and_terminal_opens(server, monkeypatch, tmp_path):
    _p, base, tok = server
    ran, opened = [], []
    monkeypatch.setattr(webapp, "execute", lambda cmd, cwd: ran.append(cmd) or (0, 0.1, "ok"))
    monkeypatch.setattr(termwin, "open_window", lambda tm, cmd, cwd: opened.append((cmd, cwd)) or "@9")
    code, d = call(base, "/api/run", {"w": "@1", "i": 0, "sha": "aaa"}, tok)
    assert code == 400 and "терминале" in d["error"] and ran == []          # вслепую не запускаем
    code, d = call(base, "/api/run/term", {"w": "@1", "i": 0, "sha": "aaa"}, tok)
    assert code == 200 and d == {"id": "@9", "name": termwin.WINDOW} and opened == [("keepassxc-cli ls db.kdbx",
                                                                                       str(tmp_path))]
    code, d = call(base, "/api/run/term", {"w": "@1", "i": 1, "sha": "bbb"}, tok)
    assert code == 400 and "другой машины" in d["error"]


def test_password_not_from_telegram(server, monkeypatch):
    _p, base, tok = server
    typed = []
    monkeypatch.setattr(termwin, "type_line", lambda tm, wid, text: typed.append((wid, text)))
    monkeypatch.setattr(webapp, "verify", lambda init, token, now=None: {"id": 1, "first_name": "Владелец"})
    code, d = call(base, "/api/term/type", {"id": "@9", "text": "x"}, "", {"X-Telegram-Init-Data": "query_id=1"})
    assert code == 400 and "Telegram" in d["error"] and typed == []
    code, d = call(base, "/api/term/type", {"id": "@9", "text": "x"}, tok)        # браузер — можно
    assert code == 200 and typed == [("@9", "x")]
    for path in webapp.TERM:
        assert path in webapp.OWNER_ONLY


# ---------- pass/GPG (задача 40) больше нет ----------
def test_no_pass_code_left():
    src = ROOT / "src" / "gas_pult"
    assert not (src / "passcheck.py").exists()
    py = "\n".join(p.read_text() for p in src.glob("*.py"))
    for gone in ("passcheck", "pass_unlock", "pass-unlock", "boot_check", "PASS_LOCKED"):
        assert gone not in py, gone
    assert not re.search(r"/api/pass[\"/?]", py)
    html = (src / "web" / "index.html").read_text()
    assert not re.search(r"/api/pass[\"/?]", html)
    for gone in ("passUnlock", "serverSheet", "pass-unlock", "passLockedNote", "data-pass-unlock"):
        assert gone not in html, gone
    assert "settings.server" not in (src / "help" / "screens.toml").read_text()
    assert not hasattr(commands.Commands("x", Path("/nonexistent"), [], []), "guard")


def test_e2e_terminal_in_browser():
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    web = ROOT / "src" / "gas_pult" / "web"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(web)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    spec = importlib.util.spec_from_file_location("term_demo", ROOT / "tests" / "e2e" / "term_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
