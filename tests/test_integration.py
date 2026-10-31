"""Сквозной тест без сети: настоящий tmux (изолированный сервер), фальшивый `claude`, фальшивый Telegram."""

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time

import pytest

from gas_pult import transcripts
from gas_pult.bot import Pult
from gas_pult.config import Config

pytestmark = pytest.mark.skipif(not shutil.which("tmux"), reason="нужен tmux")


class FakeApi:
    def __init__(self):
        self.calls = []

    def __call__(self, method, files=None, **params):
        self.calls.append((method, params))
        return {"username": "test_bot"} if method == "getMe" else {}

    def redact(self, text):
        return str(text)

    def texts(self):
        return [p.get("text", "") for m, p in self.calls if m == "sendMessage"]


def wait(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


@pytest.fixture
def tmux_socket(monkeypatch):
    """Свой сервер tmux по короткому сокету (`tmux -S`). 31.10 13:27 проверка с TMUX_TMPDIR в длинном каталоге:
    путь сокета не поместился (лимит ~104 знака), и остановка «тестового» сервера закрыла боевой с 5 окнами.
    Поэтому — только явный `-S` с коротким путём и проверкой длины; без `-S` tmux в тестах не вызываем."""
    d = tempfile.mkdtemp(prefix="gp-", dir="/tmp")
    sock = os.path.join(d, "s")
    assert len(sock) < 100
    monkeypatch.setenv("GAS_PULT_TMUX_SOCKET", sock)
    monkeypatch.delenv("TMUX", raising=False)
    yield sock
    subprocess.run(["tmux", "-S", sock, "kill-server"], capture_output=True)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def pult(tmp_path, monkeypatch, tmux_socket):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", tmp_path / "claude-projects")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"            # «Claude»: показывает приглашение и печатает всё введённое
    fake.write_text("#!/usr/bin/env bash\nwhile true; do printf '❯ '; read -r line; echo \"got: $line\"; done\n")
    fake.chmod(0o755)
    proj = tmp_path / "projects" / "demo"
    proj.mkdir(parents=True)
    cfg = Config(token="t", owners=[1], session="test", claude=str(fake), host="box",
                 project_roots=[str(tmp_path / "projects")])
    p = Pult(cfg)
    p.api = FakeApi()
    p.home = str(tmp_path)
    assert p.tmux.socket == tmux_socket                 # не боевой сервер
    yield p, proj


def msg(text):
    return {"message_id": 1, "chat": {"id": 1}, "from": {"id": 1}, "text": text}


def test_new_session_send_and_receive(pult):
    p, proj = pult
    p.open_session(1, "demo-1", str(proj))
    assert wait(lambda: (p.active() or {}).get("path") == str(proj))   # tmux узнаёт папку не мгновенно
    w = p.active()
    assert w["cmd"] == "claude" and w["name"] == "demo-1"
    assert any("активно" in t for t in p.api.texts())

    p.on_message(msg("привет, Claude"))                      # Telegram → окно
    assert wait(lambda: "got: привет, Claude" in "\n".join(p.tmux.screen(w["id"])))

    threading.Thread(target=p.monitor, daemon=True).start()  # транскрипт → Telegram
    time.sleep(1)
    d = transcripts.project_dir(str(proj))
    d.mkdir(parents=True)
    rows = [{"type": "user", "message": {"content": "вопрос"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "."}], "stop_reason": "end_turn"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Готово:\n```bash\necho ok\n```"}],
                                              "stop_reason": "end_turn"}}]
    (d / "s.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert wait(lambda: any(t.startswith("[demo-1]\nГотово") for t in p.api.texts()))
    assert not any(t == "[demo-1]\n." for t in p.api.texts())            # точку не прислали
    assert wait(lambda: any("команда 1/1" in t for t in p.api.texts()))  # команда — отдельным сообщением


def test_settings_reject_unknown_values(pult):
    p, _ = pult
    p.on_callback({"id": "q", "from": {"id": 1}, "message": {"chat": {"id": 1}}, "data": "set:notify=everything"})
    p.on_callback({"id": "q", "from": {"id": 1}, "message": {"chat": {"id": 1}}, "data": "set:owners=1"})
    assert p.state()["notify"] == "all" and "owners" not in p.state()
    p.on_callback({"id": "q", "from": {"id": 1}, "message": {"chat": {"id": 1}}, "data": "set:notify=off"})
    assert p.state()["notify"] == "off"


@pytest.mark.parametrize("argv, ok", [
    (["claude", "--resume"], True),
    (["/home/u/.local/bin/claude"], True),
    (["node", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"], True),
    (["bash", "/tmp/claude"], True),
    (["bash"], False),
    (["vim", "claude.md"], False),
])
def test_is_claude(argv, ok):
    from gas_pult.tmux import is_claude
    assert is_claude(argv) is ok


def test_one_window_per_project(pult):
    p, proj = pult
    p.open_session(1, "demo-1", str(proj))
    assert wait(lambda: (p.active() or {}).get("path") == str(proj))
    first = p.active()["id"]
    p.open_session(1, "demo-2", str(proj))                  # вторая сессия в той же папке — не создаётся
    assert p.active()["id"] == first
    assert len([w for w in p.tmux.windows() if w["cmd"] == "claude"]) == 1
    assert "уже работает «demo-1»" in p.api.texts()[-1]


class Screens:
    """tmux, у которого экран меняется по сценарию; запоминает нажатые клавиши и вставки."""
    def __init__(self, *screens, cmd="claude"):
        self.screens, self.keys_sent, self.pasted, self.cmd = list(screens), [], [], cmd

    def window(self, wid):
        return {"id": wid, "cmd": self.cmd, "mark": "claude"}

    def screen(self, wid, n=25):
        return self.screens[0].splitlines()

    def keys(self, wid, *keys):
        self.keys_sent += keys
        if len(self.screens) > 1:
            self.screens.pop(0)

    def paste(self, wid, text):
        self.pasted.append(text)


def make_pult(monkeypatch, tm):
    from gas_pult import bot
    p = bot.Pult.__new__(bot.Pult)
    p.tmux = tm
    monkeypatch.setattr(bot.time, "sleep", lambda s: None)
    return p, bot


PROMPT = "● готово\n──────\n❯ \n──────\n  ⏵⏵ auto mode on"
PANEL = "  Settings   Status   Config   Usage   Stats\n  Current session\n  Esc to cancel"


def test_text_after_open_menu_closes_menu_first(monkeypatch):
    tm = Screens(PANEL, PROMPT)
    p, _ = make_pult(monkeypatch, tm)
    p.to_claude({"id": "@1"}, "привет")
    assert tm.keys_sent == ["Escape"] and tm.pasted == ["привет"]


def test_question_is_not_answered_for_human(monkeypatch):
    tm = Screens(" Do you want to proceed?\n ❯ 1. Yes\n   2. No")
    p, bot = make_pult(monkeypatch, tm)
    with pytest.raises(bot.NotReady, match="ждёт ответа"):
        p.to_claude({"id": "@1"}, "привет")
    assert tm.keys_sent == [] and tm.pasted == []          # ни Esc, ни вставки


def test_busy_claude_still_takes_queued_text(monkeypatch):
    tm = Screens("✻ Working… (12s · esc to interrupt)\n──────\n❯ \n──────")
    p, _ = make_pult(monkeypatch, tm)
    p.to_claude({"id": "@1"}, "ещё")
    assert tm.keys_sent == [] and tm.pasted == ["ещё"]


def test_not_ready_is_reported_not_pasted_blind(monkeypatch):
    tm = Screens("Loading…")
    p, bot = make_pult(monkeypatch, tm)
    with pytest.raises(bot.NotReady, match="не готово"):
        p.to_claude({"id": "@1"}, "привет")
    assert tm.pasted == []


def test_open_menu_is_one_message_edited_in_place(monkeypatch):
    from gas_pult import bot
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = type("C", (), {"owners": [1]})()
    calls = []
    p.api = lambda method, **kw: calls.append((method, kw.get("message_id"))) or {"message_id": 77}
    p.screen_msg = lambda w, title: (title, {})
    clock = iter([100, 101, 110, 120])
    monkeypatch.setattr(bot.time, "time", lambda: next(clock))
    shown, w = {}, {"id": "@1"}
    p.show_dialog(w, "❯ 1. Opus\n  2. Sonnet\n  🤖 Opus · ctx used 10%", shown)       # новое меню — одно сообщение
    p.show_dialog(w, "❯ 1. Opus\n  2. Sonnet\n  🤖 Opus · ctx used 11%", shown)       # статус сменился — ничего
    p.show_dialog(w, "  1. Opus\n❯ 2. Sonnet\n  🤖 Opus · ctx used 11%", shown)       # сдвинули выбор — правим
    assert calls == [("sendMessage", None), ("editMessageText", 77)]


def test_own_numbered_message_is_not_a_question(monkeypatch):
    echo = "❯ 1. Слить PR #10 и перезапустить панель?\n  2. Начинать волну 2?\n● Понял, делаю.\n──────\n❯ \n──────"
    tm = Screens(echo)
    p, bot = make_pult(monkeypatch, tm)
    assert not bot.DIALOG.search(echo)
    p.to_claude({"id": "@1"}, "ещё")
    assert tm.pasted == ["ещё"] and tm.keys_sent == []


def test_real_menus_still_recognised():
    from gas_pult import bot
    picker = " Select model\n ❯ 1. Default\n   2. Opus\n Enter to confirm · Esc to exit"
    ask = " Какой вариант?\n ❯ 1. Первый\n   2. Второй\n Enter to select · ↑/↓ to navigate · Esc to cancel"
    perm = " Do you want to proceed?\n ❯ 1. Yes\n   2. No"
    assert all(bot.DIALOG.search(x) and bot.QUESTION.search(x) for x in (picker, ask, perm))


def test_prose_about_hints_is_not_a_menu():
    from gas_pult import bot
    prose = "● Настоящее меню узнаём по подсказке внизу («Enter to confirm», «Esc to cancel»).\n──────\n❯ \n──────"
    assert not bot.DIALOG.search(prose) and not bot.QUESTION.search(prose) and not bot.PANEL.search(prose)


def test_text_never_goes_to_bare_shell(monkeypatch):
    tm = Screens("user@host:~/p$ \n❯ ", cmd="zsh")             # Claude вышел, в окне оболочка (и даже с «❯»)
    p, bot = make_pult(monkeypatch, tm)
    with pytest.raises(bot.NotReady, match="остановлен"):
        p.to_claude({"id": "@1"}, "rm -rf что-нибудь")
    assert tm.pasted == []


def test_tests_never_touch_default_tmux_server():
    """Страховка: в тестах tmux — только с явным `-S` (свой сокет); голый kill-server закрыл бы окна владельца."""
    import pathlib
    import re
    for f in pathlib.Path(__file__).parent.glob("*.py"):
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if re.search(r"kill-server|kill-session", line) and "-S" not in line and "re.search" not in line:
                raise AssertionError(f"{f.name}:{n}: tmux без -S — заденет боевой сервер")


def test_claude_with_long_path_is_recognised(tmp_path, tmux_socket):
    """ps без -ww режет строку до 80 знаков: Claude по длинному пути (npm, глубокая папка) не узнавался."""
    from gas_pult.tmux import Tmux
    deep = tmp_path / ("очень-длинная-папка-" * 4) / "bin"
    deep.mkdir(parents=True)
    fake = deep / "claude"
    fake.write_text("#!/usr/bin/env bash\nwhile true; do read -r line; done\n")
    fake.chmod(0o755)
    assert len(str(fake)) > 120
    t = Tmux("long")
    wid = t.new_window("long", str(tmp_path), str(fake))
    assert wait(lambda: (t.window(wid) or {}).get("cmd") == "claude")
