"""Сообщения не путаются между сессиями (#178, #179 P0).

Было (13.11): владелец пишет в «штаб» — ответ приходит в «штаб · 09:39».
1. Telegram: любой текст уходил в общее «активное» окно, ответ (reply) на сообщение бота не учитывался.
2. Панель молча делала активным окно, которое открыли или продолжили, — и Telegram начинал писать туда.
3. Метка окна ``@gas_pult_sid`` указывала на чужой разговор; «Перезапустить» поднимал его вторым процессом —
   два Claude писали в один журнал (на сервере: окна @33 и @44 с ``--resume 96e379cd…``).

Стало: reply → окно исходного сообщения (карта ``tg_routes.json``, кнопки, «[имя]»); без reply — активное, и в
строке статуса видно «→ [имя]»; панель активное не меняет; второй запуск того же разговора — отказ; журнал, открытый
в другом окне, «Удалить» не уносит; карточка предупреждает, если разговор открыт в двух окнах."""

import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest

from gas_pult import bot, tgroutes, transcripts, webapp
from gas_pult.config import Config

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"


# ---------- карта «сообщение бота → окно» ----------
def test_routes_bind_get_survive_restart_and_trim(tmp_path, monkeypatch):
    f = tmp_path / "tg_routes.json"
    r = tgroutes.Routes(f)
    r.bind(1, 10, "@1")
    r.bind(1, 11, "@33")
    assert r.get(1, 10) == "@1" and r.get(1, 11) == "@33" and r.get(2, 10) is None
    assert tgroutes.Routes(f).get(1, 10) == "@1"                  # перезапуск бота — карта на диске
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    r.moved("@1", "@50")                                          # «Перезапустить» — новое окно того же разговора
    assert tgroutes.Routes(f).get(1, 10) == "@50"
    monkeypatch.setattr(tgroutes, "KEEP", 5)
    for i in range(20):
        r.bind(1, 100 + i, "@7")
    d = json.loads(f.read_text())
    assert len(d) == 5 and "1:119" in d and "1:100" not in d       # старые — вытесняются
    r.bind(0, 1, "@1")                                            # пустой чат/сообщение — не пишем
    r.bind(1, None, "@1")
    assert tgroutes.Routes(f).get(1, None) is None


def test_routes_broken_file_does_not_break(tmp_path):
    f = tmp_path / "tg_routes.json"
    f.write_text("{не json")
    r = tgroutes.Routes(f)
    assert r.get(1, 1) is None
    r.bind(1, 1, "@3")
    assert tgroutes.Routes(f).get(1, 1) == "@3"


@pytest.mark.parametrize("data,want", [
    ("act:@5", "@5"), ("key:@12|Escape", "@12"), ("scr:@3", "@3"), ("rs:@4:abcdef", "@4"),
    ("say:17", None), ("noop:", None), ("cmd:/model opus", None)])
def test_markup_wid(data, want):
    msg = {"reply_markup": {"inline_keyboard": [[{"text": "x", "callback_data": data}]]}}
    assert tgroutes.markup_wid(msg) == want


def test_head_name():
    assert tgroutes.head_name({"text": "[штаб]\nГотово"}) == "штаб"
    assert tgroutes.head_name({"text": "→ [штаб · 09:39] ⏳ Отправлено"}) == "штаб · 09:39"
    assert tgroutes.head_name({"text": "Просто текст"}) is None


# ---------- бот: ответ уходит в окно исходного сообщения ----------
class Wins:
    def __init__(self, wins):
        self.wins = wins

    def windows(self):
        return [dict(w) for w in self.wins]

    def window(self, wid):
        return next((dict(w) for w in self.wins if w["id"] == wid), None)


def two_windows():
    return [{"id": "@1", "name": "штаб", "cmd": "claude", "path": "/p/shtap", "sid": A, "channel": False},
            {"id": "@33", "name": "штаб · 09:39", "cmd": "claude", "path": "/p/shtap", "sid": B, "channel": False}]


@pytest.fixture
def tg(tmp_path):
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = Config(token="t", owners=[1])
    p.tmux = Wins(two_windows())
    p.routes = tgroutes.Routes(tmp_path / "tg_routes.json")
    p.waiting, p.task = {}, re.compile(r"^(GAS-\d+)$")
    st = {"active": "@33"}
    p.state = lambda: dict(st)
    p.got, p.sent = [], []
    p.to_claude_live = lambda chat, w, text: p.got.append((w["id"], text))
    p.react = lambda m, e: None
    p.send = lambda chat, text, **kw: p.sent.append(text) or {"message_id": 999}
    return p


def reply(text, to: dict):
    return {"message_id": 5, "chat": {"id": 1}, "from": {"id": 1}, "text": text, "reply_to_message": to}


def test_reply_goes_to_window_of_that_message_not_active(tg):
    tg.routes.bind(1, 70, "@1")                                       # ответ «штаба» пришёл сообщением 70
    tg.on_message(reply("продолжай", {"message_id": 70, "from": {"id": 9, "is_bot": True}, "text": "[штаб]\n…"}))
    assert tg.got == [("@1", "продолжай")]                            # активное — @33, но ответили «штабу»


def test_plain_message_goes_to_active(tg):
    tg.on_message({"message_id": 5, "chat": {"id": 1}, "from": {"id": 1}, "text": "привет"})
    assert tg.got == [("@33", "привет")]


def test_reply_falls_back_to_buttons_then_unique_name(tg):
    kb = {"inline_keyboard": [[{"text": "✅ Да", "callback_data": "yes:@1"}]]}
    tg.on_message(reply("а", {"message_id": 71, "from": {"is_bot": True}, "text": "[x]", "reply_markup": kb}))
    tg.on_message(reply("б", {"message_id": 72, "from": {"is_bot": True}, "text": "→ [штаб] ✅ Готово · 5 с"}))
    assert tg.got == [("@1", "а"), ("@1", "б")]
    tg.tmux.wins.append({"id": "@40", "name": "штаб", "cmd": "claude", "path": "/p/x", "sid": "", "channel": False})
    tg.on_message(reply("в", {"message_id": 73, "from": {"is_bot": True}, "text": "[штаб]\n…"}))
    assert tg.got[-1] == ("@33", "в")                                 # имя не одно — не угадываем, активное


def test_reply_to_gone_or_stopped_window_is_refused_not_rerouted(tg):
    tg.routes.bind(1, 80, "@9")                                       # окна @9 уже нет
    tg.on_message(reply("ещё", {"message_id": 80, "from": {"is_bot": True}, "text": "[старое]"}))
    tg.tmux.wins[0]["cmd"] = "bash"                                   # в «штабе» Claude остановлен
    tg.routes.bind(1, 81, "@1")
    tg.on_message(reply("ещё", {"message_id": 81, "from": {"is_bot": True}, "text": "[штаб]"}))
    assert tg.got == []                                               # в активное @33 не ушло
    assert "уже нет" in tg.sent[0] and "остановлен" in tg.sent[1]


def test_reply_to_human_message_is_not_a_route(tg):
    tg.routes.bind(1, 90, "@1")
    tg.on_message(reply("x", {"message_id": 90, "from": {"id": 1, "is_bot": False}, "text": "моё"}))
    assert tg.got == [("@33", "x")]


def test_status_line_names_the_window():
    assert bot.Pult.to_head({"id": "@1", "name": "штаб"}) == "→ [штаб] "
    assert bot.Pult.to_head({"id": "@1"}) == ""


class Api:
    def __init__(self):
        self.calls, self.n = [], 100

    def __call__(self, method, files=None, **params):
        self.calls.append((method, params))
        if method == "sendMessage":
            self.n += 1
            return {"message_id": self.n}
        return {}

    def redact(self, text):
        return str(text)


def test_answers_dialogs_and_screens_are_bound_to_their_window(tmp_path, monkeypatch):
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = Config(token="t", owners=[1, 2])
    p.api, p.pause_until, p.skipped = Api(), 0.0, 0
    p.routes = tgroutes.Routes(tmp_path / "r.json")
    p.lock, p.counter, p.answers, p.hint_wait = threading.Lock(), 0, {}, {}
    p.cmds = type("C", (), {"offer": lambda *a: None})()
    p.state = lambda: {"voice_always": False}
    w = {"id": "@1", "name": "штаб", "path": "/p"}
    p.deliver(w, "длинный ответ " * 700)                              # два куска — оба ведут в окно
    sent = [prm["chat_id"] for m, prm in p.api.calls if m == "sendMessage"]
    assert len(sent) > 2                                              # длинный ответ — несколько кусков
    assert all(p.routes.get(c, 101 + i) == "@1" for i, c in enumerate(sent))   # любой кусок ведёт в окно
    p.tmux = type("T", (), {"screen": lambda self, wid, n=25: ["❯ 1. Да"]})()
    p.send_screen(1, {"id": "@33", "name": "штаб · 09:39"}, "экран:")
    assert p.routes.get(1, p.api.n) == "@33"


# ---------- сквозной: настоящий tmux, два окна одного проекта ----------
@pytest.fixture
def live(tmp_path, monkeypatch):
    if not shutil.which("tmux"):
        pytest.skip("нужен tmux")
    d = tempfile.mkdtemp(prefix="gp-", dir="/tmp")
    sock = d + "/s"
    monkeypatch.setenv("GAS_PULT_TMUX_SOCKET", sock)
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", tmp_path / "claude-projects")
    fake = tmp_path / "claude"
    fake.write_text("#!/usr/bin/env bash\nwhile true; do printf '❯ '; read -r line; echo \"got: $line\"; done\n")
    fake.chmod(0o755)
    proj = tmp_path / "shtap"
    proj.mkdir()
    p = bot.Pult(Config(token="t", owners=[1], session="test", claude=str(fake), host="box"))
    p.api = Api()
    assert p.tmux.socket == sock
    yield p, proj, fake
    subprocess.run(["tmux", "-S", sock, "kill-server"], capture_output=True)
    shutil.rmtree(d, ignore_errors=True)


def wait(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


def test_two_sessions_one_project_messages_do_not_mix(live):
    p, proj, fake = live
    p.actor.uid = None                                                # кто действует — как в боте до проверки страны
    a = p.tmux.new_window("штаб", str(proj), str(fake), sid=A)
    b = p.tmux.new_window("штаб · 09:39", str(proj), str(fake), sid=B)
    assert wait(lambda: all((p.tmux.window(x) or {}).get("cmd") == "claude" for x in (a, b)))
    p.set_state(active=b)                                             # активное — второе окно
    p.deliver(p.tmux.window(a), "Готово, жду указаний")              # ответ первого окна пришёл в Telegram
    mid = next(prm for m, prm in p.api.calls if m == "sendMessage" and "Готово" in prm["text"])
    msg_id = p.api.n
    assert mid
    p2 = bot.Pult(p.cfg)                                              # бот перезапустили — карта на диске
    p2.api = p.api
    p2.on_message(reply("пиши в штаб", {"message_id": msg_id, "from": {"is_bot": True}, "text": "[штаб]\n…"}))
    assert wait(lambda: "got: пиши в штаб" in "\n".join(p.tmux.screen(a)))
    p2.on_message({"message_id": 6, "chat": {"id": 1}, "from": {"id": 1}, "text": "а это — во второе"})
    assert wait(lambda: "got: а это — во второе" in "\n".join(p.tmux.screen(b)))
    time.sleep(0.5)
    assert "во второе" not in "\n".join(p.tmux.screen(a))
    assert "пиши в штаб" not in "\n".join(p.tmux.screen(b))
    status = [prm["text"] for m, prm in p.api.calls if m == "sendMessage" and "Отправлено" in prm.get("text", "")]
    assert status[0].startswith("→ [штаб] ") and status[1].startswith("→ [штаб · 09:39] ")


# ---------- панель: активное окно бота — только явным выбором ----------
@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    state = {"active": "@2"}
    monkeypatch.setattr(p.pult, "state", lambda: dict(state))
    monkeypatch.setattr(p.pult, "set_state", lambda **kw: state.update(kw))
    monkeypatch.setattr(p, "need_claude", lambda: None)
    opened = []
    monkeypatch.setattr(p.tmux, "new_window", lambda name, path, cmd, **kw: opened.append(cmd) or "@11")
    monkeypatch.setattr(p, "mark_by", lambda wid, uid: None)
    monkeypatch.setattr(webapp.models, "command", lambda base, profile, st, **kw: "claude")
    p.t = {"state": state, "opened": opened}
    return p


def test_new_session_does_not_steal_bot_active(panel, tmp_path):
    panel.open_in(str(tmp_path), "", None, None)
    panel.open_in(str(tmp_path), "", None, None, model="opus")
    assert panel.t["state"]["active"] == "@2"


def test_existing_project_window_does_not_steal_bot_active(panel, monkeypatch, tmp_path):
    monkeypatch.setattr(panel.pult, "projects", lambda: [str(tmp_path)])
    monkeypatch.setattr(panel.pult, "project_window", lambda path: {"id": "@7", "name": "x"})
    assert panel.new(0) == {"id": "@7", "existing": "x"}
    assert panel.t["state"]["active"] == "@2"


# ---------- один разговор — одно окно ----------
def wins_panel(panel, monkeypatch, wins):
    monkeypatch.setattr(panel.tmux, "windows", lambda: [dict(w) for w in wins])
    monkeypatch.setattr(panel.tmux, "window", lambda wid: next((dict(w) for w in wins if w["id"] == wid), None))
    monkeypatch.setattr(panel.pult, "home_of", lambda w: None)


def test_revive_refuses_conversation_live_in_other_window(panel, monkeypatch):
    wins = [{"id": "@1", "name": "штаб", "cmd": "bash", "mark": "claude", "path": "/p", "sid": A, "stopped": True},
            {"id": "@33", "name": "штаб · 09:39", "cmd": "claude", "mark": "claude", "path": "/p", "sid": A}]
    wins_panel(panel, monkeypatch, wins)
    respawned = []
    monkeypatch.setattr(panel.tmux, "respawn", lambda *a, **kw: respawned.append(a))
    with pytest.raises(ValueError, match="уже открыт в окне «штаб · 09:39»"):
        panel.revive("@1")
    assert respawned == []
    wins[1]["sid"] = B                                                # разговоры разные — перезапуск можно
    assert panel.revive("@1") == {"id": "@1"} and respawned


def test_restart_keep_refuses_conversation_live_in_other_window(panel, monkeypatch):
    wins = [{"id": "@1", "name": "штаб", "cmd": "claude", "mark": "claude", "path": "/p", "sid": A, "by": ""},
            {"id": "@33", "name": "штаб · 09:39", "cmd": "claude", "mark": "claude", "path": "/p", "sid": A}]
    wins_panel(panel, monkeypatch, wins)
    closed = []
    monkeypatch.setattr(panel, "close", lambda w: closed.append(w["id"]) or "закрыто")
    with pytest.raises(ValueError, match="уже открыт"):
        panel.restart(dict(wins[0]), "claude")
    assert closed == [] and panel.t["opened"] == []                   # окно не закрыто, второй процесс не запущен
    panel.restart(dict(wins[0]), "claude", keep=False)                # чистый лист — можно
    assert closed == ["@1"]


def test_sid_owner_and_twin_flag(panel, monkeypatch):
    wins = [{"id": "@1", "name": "a", "cmd": "claude", "path": "/p", "sid": A},
            {"id": "@2", "name": "b", "cmd": "bash", "mark": "claude", "stopped": True, "path": "/p", "sid": B},
            {"id": "@3", "name": "c", "cmd": "claude", "path": "/p", "sid": A, "space": "demo"}]
    assert panel.sid_owner(A, "@9", wins)["id"] == "@1"
    assert panel.sid_owner(A, "@1", wins) is None                     # окно пространства — не наше
    assert panel.sid_owner(B, "", wins)["id"] == "@2"
    assert panel.sid_owner(B, "", wins, running=True) is None
    assert panel.sid_owner("", "", wins) is None


def test_follow_sid_never_takes_journal_of_another_window(panel, monkeypatch, tmp_path):
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", tmp_path / "cp")
    d = transcripts.project_dir("/p")
    d.mkdir(parents=True)
    (d / f"{A}.jsonl").write_text('{"type":"user","message":{"content":"a"}}\n')
    time.sleep(0.02)
    (d / f"{B}.jsonl").write_text('{"type":"user","message":{"content":"b"}}\n')   # новее — журнал окна @2
    sets = []
    monkeypatch.setattr(panel.tmux, "set_sid", lambda wid, sid: sets.append((wid, sid)))
    w = {"id": "@1", "cmd": "claude", "path": "/p", "sid": A}
    stopped = {"id": "@2", "cmd": "bash", "stopped": True, "mark": "claude", "path": "/p", "sid": B}
    assert panel.follow_sid(dict(w), [w, stopped], None) == A and sets == []   # раньше метка уезжала на B
    assert panel.follow_sid(dict(w), [w], None) == B                         # ничей новый журнал (/clear) — наш


def test_delete_keeps_journal_open_in_other_window(panel, monkeypatch, tmp_path):
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", tmp_path / "cp")
    d = transcripts.project_dir("/p")
    d.mkdir(parents=True)
    (d / f"{A}.jsonl").write_text('{"type":"user","message":{"content":"a"}}\n')
    wins = [{"id": "@1", "name": "штаб", "cmd": "bash", "mark": "claude", "path": "/p", "sid": A, "stopped": True},
            {"id": "@33", "name": "штаб · 09:39", "cmd": "claude", "mark": "claude", "path": "/p", "sid": A}]
    wins_panel(panel, monkeypatch, wins)
    killed = []
    monkeypatch.setattr(panel.tmux, "kill", lambda wid: killed.append(wid))
    monkeypatch.setattr(panel, "project_data", lambda *a, **kw: {})
    out = panel.chat_delete("@1")
    assert killed == ["@1"] and out["kept"] == "штаб · 09:39" and out["trash"] is None
    assert (d / f"{A}.jsonl").is_file()                               # живой разговор соседнего окна на месте


def test_bot_routes_follow_restarted_window(panel, monkeypatch, tmp_path):
    wins = [{"id": "@1", "name": "штаб", "cmd": "claude", "mark": "claude", "path": "/p", "sid": A, "by": ""}]
    wins_panel(panel, monkeypatch, wins)
    monkeypatch.setattr(panel, "close", lambda w: "закрыто")
    panel.pult.routes = tgroutes.Routes(tmp_path / "r.json")
    panel.pult.routes.bind(1, 5, "@1")
    panel.restart(dict(wins[0]), "claude")
    assert panel.pult.routes.get(1, 5) == "@11"


def test_card_warns_about_twin():
    html = (Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html").read_text()
    assert "s.twin ?" in html and "ответы смешиваются" in html
