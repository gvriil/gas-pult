"""Живая строка статуса: журнал Claude Code → что агент делает сейчас; фазы до хода; API панели; правки в боте.

Журналы — выдуманные, во временной папке. Живой tmux и настоящий Claude не нужны."""

import json
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer

import pytest

from gas_pult import activity as a
from gas_pult import bot, transcripts, webapp, webauth
from gas_pult.config import Config
from gas_pult.telegram import TelegramError

T0 = 1793520000.0                    # 2026-11-02 08:00:00 UTC


def ts(sec: float) -> str:
    return datetime.fromtimestamp(T0 + sec, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def jsonl(*entries) -> str:
    return "".join(json.dumps(e) + "\n" for e in entries)


def prompt(text, t=0):
    return {"type": "user", "timestamp": ts(t), "message": {"role": "user", "content": text}}


def use(name, arg, tid="t1", t=1, stop="tool_use"):
    return {"type": "assistant", "timestamp": ts(t),
            "message": {"stop_reason": stop, "content": [{"type": "tool_use", "id": tid, "name": name, "input": arg}]}}


def result(tid="t1", t=2):
    return {"type": "user", "timestamp": ts(t),
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": "ok"}]}}


def think(t=1, stop="tool_use"):
    return {"type": "assistant", "timestamp": ts(t), "message": {"stop_reason": stop,
                                                               "content": [{"type": "thinking", "thinking": "…"}]}}


def say(text, t=3, stop="end_turn"):
    return {"type": "assistant", "timestamp": ts(t), "message": {"stop_reason": stop,
                                                               "content": [{"type": "text", "text": text}]}}


# ---------- разбор журнала ----------
@pytest.mark.parametrize("name, arg, want", [
    ("Read", {"file_path": "/home/u/projects/x/src/web/index.html"}, "Читает файл index.html"),
    ("Edit", {"file_path": "/a/b/bot.py", "old_string": "x"}, "Правит файл bot.py"),
    ("MultiEdit", {"file_path": "/a/b/bot.py"}, "Правит файл bot.py"),
    ("Write", {"file_path": "/a/b/new.md", "content": "…"}, "Создаёт файл new.md"),
    ("NotebookEdit", {"notebook_path": "/a/n.ipynb"}, "Правит файл n.ipynb"),
    ("Grep", {"pattern": "def to_claude"}, "Ищет в коде: def to_claude"),
    ("Glob", {"pattern": "**/*.py"}, "Ищет в коде: **/*.py"),
    ("WebSearch", {"query": "погода в Амстердаме"}, "Ищет в интернете: погода в Амстердаме"),
    ("WebFetch", {"url": "https://www.site.ru/path/page?token=abc"}, "Открывает ссылку site.ru"),
    ("Bash", {"command": "pytest -q", "description": "Прогнать тесты"}, "Выполняет команду: Прогнать тесты"),
    ("Bash", {"command": "ls -la"}, "Выполняет команду: ls -la"),
    ("Agent", {"description": "Разобрать журнал", "prompt": "…"}, "Запустил помощника: Разобрать журнал"),
    ("Task", {"description": "Поиск"}, "Запустил помощника: Поиск"),
    ("TodoWrite", {"todos": []}, "Обновляет план"),
    ("mcp__claude_ai_Notion__notion-search", {"query": "x"}, "Работает с Notion"),
    ("mcp__github__get_me", {}, "Работает с github"),
    ("FancyNewTool", {}, "Работает: FancyNewTool"),
])
def test_tool_words(name, arg, want):
    st = a.parse([prompt("сделай"), use(name, arg)])
    assert st["phase"] == "working" and st["text"] == want and st["tool"] == name
    assert st["since"] == pytest.approx(T0 + 1, abs=0.01)


def test_open_vs_closed_tool_use():
    entries = [prompt("сделай"), use("Read", {"file_path": "/x/a.py"})]
    assert a.parse(entries)["phase"] == "working"
    entries.append(result())                                    # инструмент вернул результат — снова думает
    st = a.parse(entries)
    assert st["phase"] == "thinking" and st["text"] == "Думает…"
    entries.append(use("Bash", {"command": "make"}, "t2", 4))   # следующий инструмент — он «сейчас»
    assert a.parse(entries)["text"] == "Выполняет команду: make"


def test_thinking_started_and_done():
    assert a.parse([prompt("привет")])["phase"] == "started"
    assert a.parse([prompt("привет")])["text"] == "Взял в работу"
    st = a.parse([prompt("привет"), think(1, "end_turn")])     # размышление с end_turn — ход ещё не закончен
    assert st["phase"] == "thinking"
    st = a.parse([prompt("привет"), think(1, "end_turn"), say("Готово, всё сделал.", 5)])
    assert st["phase"] == "done" and st["text"] == "Готово" and st["since"] == pytest.approx(T0 + 5, abs=0.01)
    st = a.parse([prompt("привет"), say("Сейчас посмотрю", 1, "tool_use")])
    assert st["phase"] == "thinking"


def test_turn_duration_and_interrupt_end_turn():
    e = [prompt("x"), use("Bash", {"command": "sleep 100"})]
    assert a.parse([*e, {"type": "system", "subtype": "turn_duration", "timestamp": ts(9)}])["phase"] == "done"
    assert a.parse([*e, prompt("[Request interrupted by user]", 9)])["phase"] == "done"


def test_ask_user_question_is_waiting():
    st = a.parse([prompt("x"), use("AskUserQuestion", {"questions": []})])
    assert st["phase"] == "waiting" and st["text"] == "Ждёт вашего ответа"


def test_sidechain_ignored_and_empty():
    assert a.parse([])["phase"] == "idle"
    st = a.parse([prompt("x"), {**use("Read", {"file_path": "/s.py"}), "isSidechain": True}])
    assert st["phase"] == "started"


def test_subagent_activity_added():
    st = a.parse([prompt("x"), use("Agent", {"description": "Проверка"})],
                 subagent={"phase": "working", "text": "Читает файл bot.py"})
    assert st["text"] == "Запустил помощника: Проверка · Читает файл bot.py"


def test_mask_secrets_in_commands():
    cmd = ('TOKEN=abc123 curl -H "Authorization: Bearer sk-ant-api03-aaaaaaaaaaaa" '
           "https://user:hunter2@example.com/?api_key=zzz --password hunter2 ghp_abcdefghijklmnop12345")
    out = a.mask(cmd)
    for secret in ("abc123", "sk-ant", "hunter2", "zzz", "ghp_abc"):
        assert secret not in out
    assert "curl" in out and "example.com" in out
    assert a.mask("ls -la src") == "ls -la src"
    st = a.parse([prompt("x"), use("Bash", {"command": "export OPENAI_API_KEY=sk-proj-0123456789abcdef && run"})])
    assert "sk-proj" not in st["text"] and "0123456789" not in st["text"]


def test_long_text_clipped():
    st = a.parse([prompt("x"), use("Bash", {"command": "echo " + "a b " * 100})])
    assert len(st["text"]) <= len("Выполняет команду: ") + 50 and st["text"].endswith("…")
    st = a.parse([prompt("x"), use("Read", {"file_path": "/x/" + "долгое-имя-" * 10 + ".py"})])
    assert len(st["text"]) <= len("Читает файл ") + 48


def test_spinner_from_screen():
    assert a.spinner(["", "✻ Pondering… (12s · ↓ 1.2k tokens · esc to interrupt)", "❯ "]) == "Pondering… · 12s"
    assert a.spinner(["· Thinking… (esc to interrupt)"]) == "Thinking…"
    assert a.spinner(["● Bash(npm test)", "  ⎿  24 passed", "❯ "]) == ""


def test_journal_reads_tail_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", tmp_path / "projects")
    d = transcripts.project_dir("/w/proj")
    d.mkdir(parents=True)
    f = d / "s1.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in [prompt("x"), use("Read", {"file_path": "/w/a.py"})]) + "\n")
    j = a.Journal()
    calls = []
    real = a.parse
    monkeypatch.setattr(a, "parse", lambda *x, **k: calls.append(1) or real(*x, **k))
    assert j.status("/w/proj")["text"] == "Читает файл a.py"
    assert j.status("/w/proj")["text"] == "Читает файл a.py" and len(calls) == 1      # тот же размер — из кэша
    with open(f, "a") as fh:
        fh.write(json.dumps(result()) + "\n")
    assert j.status("/w/proj")["phase"] == "thinking" and len(calls) == 2
    # у участника — своя папка Claude Code (home): журналы владельца ему не видны
    home = tmp_path / "people" / "7" / "claude"
    assert j.status("/w/proj", home)["phase"] == "idle"


def test_journal_subagent(tmp_path, monkeypatch):
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", tmp_path / "projects")
    d = transcripts.project_dir("/w/p")
    (d / "s1" / "subagents").mkdir(parents=True)
    (d / "s1.jsonl").write_text(jsonl(prompt("x"), use("Agent", {"description": "Ревью"})))
    (d / "s1" / "subagents" / "agent-1.jsonl").write_text(jsonl(prompt("задание"), use("Grep", {"pattern": "TODO"})))
    assert a.Journal().status("/w/p")["text"] == "Запустил помощника: Ревью · Ищет в коде: TODO"


# ---------- фазы до хода ----------
class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def test_phases_sent_delivered_taken():
    clock = Clock(T0 + 100)
    s = a.Sends(clock)
    journal = a.parse([prompt("старое", 0), say("ответ", 3)])          # прошлый ход закончен
    s.sent("@1", "новое")
    assert a.combine(journal, s.get("@1"), {}, clock.t)["phase"] == "sent"
    clock.t += 1
    s.delivered("@1")
    st = a.combine(journal, s.get("@1"), {}, clock.t)
    assert st["phase"] == "delivered" and st["text"] == "Доставлено в сессию" and st["since"] == clock.t
    clock.t += 2                                                       # в журнале появился наш запрос
    journal = a.parse([prompt("старое", 0), say("ответ", 3), prompt("новое", 102)])
    st = a.combine(journal, s.get("@1"), {}, clock.t, sends=s, wid="@1")
    assert st["phase"] == "started" and st["text"] == "Взял в работу"
    assert s.get("@1") is None                                         # дальше — только журнал


def test_no_reaction_busy_vs_stuck():
    clock = Clock(T0 + 100)
    s = a.Sends(clock)
    s.sent("@1", "x")
    s.delivered("@1")
    idle = a.parse([prompt("старое", 0), say("ответ", 3)])
    clock.t += 19
    assert a.combine(idle, s.get("@1"), {"busy": False}, clock.t)["phase"] == "delivered"
    clock.t += 2                                                       # 21 с без нового хода
    st = a.combine(idle, s.get("@1"), {"busy": False}, clock.t)
    assert st["phase"] == "stuck" and st["action"] == "screen" and "показать экран" in st["text"]
    st = a.combine(idle, s.get("@1"), {"busy": True}, clock.t)          # окно занято прошлой задачей
    assert st["phase"] == "queued" and "в очереди" in st["text"]
    working = a.parse([prompt("старое", 0), use("Bash", {"command": "make"}, t=90)])
    assert a.combine(working, s.get("@1"), None, clock.t)["phase"] == "queued"


def test_queue_in_claude_code_then_picked():
    clock = Clock(T0 + 100)
    s = a.Sends(clock)
    s.sent("@1", "ещё")
    s.delivered("@1")
    busy = [prompt("старое", 0), use("Bash", {"command": "make"}, t=90)]
    enq = {"type": "queue-operation", "operation": "enqueue", "timestamp": ts(101), "content": "ещё"}
    st = a.combine(a.parse([*busy, enq]), s.get("@1"), {"busy": True}, clock.t + 2)
    assert st["phase"] == "queued" and "в очереди" in st["text"]              # честно сразу, не ждём 20 с
    picked = {"type": "attachment", "timestamp": ts(110), "attachment": {"type": "queued_command", "prompt": "ещё"}}
    rm = {"type": "queue-operation", "operation": "remove", "timestamp": ts(110)}
    st = a.combine(a.parse([*busy, enq, rm, picked]), s.get("@1"), {"busy": True}, clock.t + 12, sends=s, wid="@1")
    assert st["phase"] == "working" and s.get("@1") is None                  # прочитал по ходу работы — взял


def test_send_failed_forgets():
    s = a.Sends()
    s.sent("@1", "x")
    s.failed("@1")
    assert s.get("@1") is None


def test_dialog_on_screen_is_waiting_and_spinner():
    j = a.parse([prompt("x"), use("Bash", {"command": "rm -rf dist"})])
    st = a.combine(j, None, {"busy": False, "dialog": True}, T0 + 2)
    assert st["phase"] == "waiting" and st["action"] == "answer"
    st = a.combine(j, None, {"busy": True, "dialog": False, "spinner": "Pondering… · 3s"}, T0 + 2)
    assert st["phase"] == "working" and st["spinner"] == "Pondering… · 3s"


def test_stale_journal_with_idle_screen_is_done():
    j = a.parse([prompt("x"), use("Bash", {"command": "make"})])
    assert a.combine(j, None, {"busy": False}, T0 + 5)["phase"] == "working"     # только что — верим журналу
    assert a.combine(j, None, {"busy": False}, T0 + 60)["phase"] == "done"       # экран давно свободен — прерван


def test_bot_line():
    st = {"phase": "working", "text": "Читает файл X", "since": T0, "spinner": ""}
    assert a.line(st, T0 + 12, started=True) == "✅ Взял в работу · Читает файл X · 12 с"
    assert a.line({"phase": "sent"}) == "⏳ Отправлено"
    assert a.elapsed(75) == "1 мин 15 с" and a.elapsed(3700) == "1 ч 1 мин"


def test_to_claude_records_delivery(monkeypatch, tmp_path):
    p = bot.Pult.__new__(bot.Pult)
    p.sends, p.locks = a.Sends(), tmp_path / "locks"
    p.tmux = type("T", (), {"paste": lambda self, wid, text: None})()
    monkeypatch.setattr(p, "ready_for_text", lambda wid: None)
    assert p.to_claude({"id": "@1"}, "привет") is True
    assert p.sends.get("@1")["delivered_at"]
    p.tmux = type("T", (), {"paste": lambda self, wid, text: (_ for _ in ()).throw(RuntimeError("нет"))})()
    with pytest.raises(RuntimeError):
        p.to_claude({"id": "@1"}, "ещё")
    assert p.sends.get("@1") is None                          # не дошло — «Доставлено» не покажем


# ---------- бот: одно сообщение, правки по фазам ----------
def follower(phases, clock):
    p = bot.Pult.__new__(bot.Pult)
    p.lock, p.following, p.pause_until, p.calls = threading.Lock(), {}, 0.0, []
    seq = iter(phases)

    def api(method, **kw):
        p.calls.append((method, kw.get("text", "")))
        return {"message_id": 5}

    def step():
        ph = next(seq)
        return {"phase": ph, "text": a.TEXTS.get(ph) or "Читает файл x.py", "since": clock.t - 4, "spinner": "",
                "action": ""}

    p.api, p.activity = api, lambda w: step()
    return p


def test_bot_edits_one_message_and_throttles():
    clock = Clock()
    p = follower(["delivered", "delivered", "started", "working", "working", "done"], clock)
    sleeps = []

    def sleep(sec):
        sleeps.append(sec)
        clock.t += sec

    p.follow(1, 5, {"id": "@1"}, clock=clock, sleep=sleep)
    methods = {m for m, _ in p.calls}
    assert methods == {"editMessageText"}                     # ни одного нового сообщения
    texts = [t for _, t in p.calls]
    assert texts[0].startswith("📨 Доставлено в сессию")
    assert any(t.startswith("✅ Взял в работу") for t in texts)
    assert texts[-1].startswith("✅ Готово")
    assert len(texts) == len(set(texts))                      # одинаковый текст второй раз не правим
    assert all(s >= bot.Pult.FOLLOW_EVERY for s in sleeps)    # не чаще раза в 3 с
    assert p.following == {}


def test_bot_stops_quietly_when_message_deleted():
    clock = Clock()
    p = follower(["delivered", "started", "working"], clock)

    def api(method, **kw):
        p.calls.append(method)
        raise TelegramError(method, "Bad Request: message to edit not found")

    p.api = api
    p.follow(1, 5, {"id": "@1"}, clock=clock, sleep=lambda s: setattr(clock, "t", clock.t + s))
    assert p.calls == ["editMessageText"]


def test_bot_stuck_has_screen_button():
    clock = Clock()
    p = follower(["stuck", "done"], clock)
    kws = []
    p.api = lambda method, **kw: kws.append(kw) or {}
    p.FOLLOW_MAX = 7
    p.follow(1, 5, {"id": "@1"}, clock=clock, sleep=lambda s: setattr(clock, "t", clock.t + s))
    assert "scr:@1" in json.dumps(kws[0]["reply_markup"])


def test_bot_live_send_sends_status_once(monkeypatch):
    p = bot.Pult.__new__(bot.Pult)
    p.pause_until, sent, started = 0.0, [], []
    p.api = lambda method, **kw: sent.append((method, kw.get("text"))) or {"message_id": 9}
    monkeypatch.setattr(p, "to_claude", lambda w, text: True)
    monkeypatch.setattr(bot.threading, "Thread", lambda target, args, daemon: type(
        "Th", (), {"start": lambda self: started.append(args)})())
    p.to_claude_live(1, {"id": "@1"}, "привет")
    assert sent == [("sendMessage", "⏳ Отправлено")] and started == [(1, 9, {"id": "@1"})]
    monkeypatch.setattr(p, "to_claude", lambda w, text: (_ for _ in ()).throw(bot.NotReady("занято")))
    sent.clear()
    with pytest.raises(bot.NotReady):
        p.to_claude_live(1, {"id": "@1"}, "привет")
    assert [m for m, _ in sent] == ["sendMessage", "deleteMessage"]   # не дошло — служебное убрали


# ---------- API панели ----------
@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(transcripts, "CLAUDE_PROJECTS", tmp_path / "projects")
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.add(3, "viewer")
    for uid in (1, 3):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    d = transcripts.project_dir("/w/proj")
    d.mkdir(parents=True)
    (d / "s.jsonl").write_text(jsonl(prompt("x"), use("Read", {"file_path": "/w/a.py"})))
    wins, screens = [], []
    monkeypatch.setattr(p.tmux, "windows", lambda: wins.append(1) or [
        {"id": "@1", "path": "/w/proj", "cmd": "claude", "by": "", "name": "proj"}])
    monkeypatch.setattr(p.tmux, "screen", lambda wid, n=25: screens.append(1) or [
        "✻ Pondering… (3s · esc to interrupt)", "❯ "])
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    p.wins_calls, p.screen_calls = wins, screens
    yield p, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def get(base, path, token=""):
    req = urllib.request.Request(base + path, headers={"Cookie": f"{webauth.COOKIE}={token}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_api_activity_rights_and_format(server):
    panel, base = server
    assert get(base, "/api/activity?w=@1")[0] == 401                    # без входа — нет
    code, d = get(base, "/api/activity?w=@1", panel.auth.issue(3))        # наблюдатель видит
    assert code == 200
    assert d["phase"] == "working" and d["text"] == "Читает файл a.py" and d["tool"] == "Read"
    assert d["spinner"] == "Pondering… · 3s" and d["since"] and d["now"] and d["rev"]
    assert get(base, "/api/activity?w=@9", panel.auth.issue(1))[0] == 404
    # опрос раз в 1,5 с: окна и экран не перечитываются на каждый запрос
    n_win, n_scr = len(panel.wins_calls), len(panel.screen_calls)
    for _ in range(3):
        get(base, "/api/activity?w=@1", panel.auth.issue(1))
    assert len(panel.wins_calls) == n_win and len(panel.screen_calls) == n_scr


def test_api_send_marks_delivered(server, monkeypatch):
    panel, base = server
    monkeypatch.setattr(panel.pult, "ready_for_text", lambda wid: None)
    monkeypatch.setattr(panel.tmux, "paste", lambda wid, text: None)
    panel.send({"id": "@1", "path": "/w/proj"}, "новое")
    panel.screens.clear()
    code, d = get(base, "/api/activity?w=@1", panel.auth.issue(1))
    assert code == 200 and d["phase"] == "delivered" and d["text"] == "Доставлено в сессию"
