"""Бот широко: кнопки и сообщения Telegram → нужное окно (задание штаба 13.11: «покрыть всё тестами»).

Раньше не покрыты половина ``on_callback`` и ``on_message`` — как раз маршрутизация из Telegram (#179 P0).
Здесь — сценарии на подменённом tmux и Telegram: каждая кнопка под ответом, экраном и списком окон действует на своё
окно; чужие кнопки не срабатывают; ушедшее окно — понятный ответ, а не действие в другом окне."""

import re
import threading

import pytest

from gas_pult import bot, tgroutes, transcripts
from gas_pult.config import Config

PROMPT = "● готово\n──────\n❯ \n──────"


class Tmux:
    def __init__(self):
        self.wins = [
            {"id": "@1", "idx": "1", "name": "штаб", "cmd": "claude", "path": "/p/shtap", "sid": "", "channel": False,
             "mark": "claude", "by": ""},
            {"id": "@33", "idx": "2", "name": "штаб · 09:39", "cmd": "claude", "path": "/p/shtap", "sid": "",
             "channel": True, "mark": "claude", "by": ""},
            {"id": "@5", "idx": "3", "name": "bash", "cmd": "bash", "path": "/p/x", "sid": "", "channel": False,
             "mark": "", "by": ""}]
        self.keys_sent, self.killed, self.typed, self.pasted, self.renamed = [], [], [], [], []
        self.screen_text = PROMPT

    def windows(self):
        return [dict(w) for w in self.wins]

    def window(self, wid):
        return next((dict(w) for w in self.wins if w["id"] == wid), None)

    def screen(self, wid, n=25):
        return self.screen_text.splitlines()

    def keys(self, wid, *k):
        self.keys_sent.append((wid, *k))

    def kill(self, wid):
        self.killed.append(wid)
        self.wins = [w for w in self.wins if w["id"] != wid]

    def type(self, wid, text):
        self.typed.append((wid, text))

    def paste(self, wid, text):
        self.pasted.append((wid, text))
        return True

    def rename(self, wid, name):
        if not name.strip():
            raise ValueError("пустое имя")
        self.renamed.append((wid, name))
        return name

    def hint(self, wid):
        return ""

    def draft(self, wid, dim=False):
        return ""


@pytest.fixture
def p(tmp_path, monkeypatch):
    x = bot.Pult.__new__(bot.Pult)
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    x.cfg = Config(token="t", owners=[1], models=["opus", "sonnet"])
    x.tmux = Tmux()
    x.routes = tgroutes.Routes(tmp_path / "r.json")
    x.waiting, x.task = {}, re.compile(r"^(?:/task\s+)?(GAS-\d+)$", re.I)
    x.home = "/p"
    x.lock, x.counter, x.answers, x.hints, x.hint_wait = threading.Lock(), 0, {}, {}, {}
    x.locks = tmp_path / "locks"
    st = {"active": "@33", "notify": "all", "voice_always": False, "voice": "irina"}
    x.state = lambda: dict(st)
    x.set_state = lambda **kw: st.update(kw)
    x.st = st
    x.sent, x.calls, x.to = [], [], (lambda chat: lambda text, **kw: x.sent.append((text, kw)) or {"message_id": 1})
    x.send = lambda chat, text, **kw: x.sent.append((text, kw)) or {"message_id": 1}
    x.api = lambda method, **kw: x.calls.append((method, kw)) or {}
    x.got = []
    x.to_claude = lambda w, text, src="": x.got.append((w["id"], text)) or True
    x.to_claude_live = lambda chat, w, text: x.got.append((w["id"], text))
    x.react = lambda m, e: None
    x.actor.uid = None
    monkeypatch.setattr(bot.time, "sleep", lambda s: None)
    monkeypatch.setattr(x, "projects", lambda: ["/p", "/p/shtap", "/p/x"], raising=False)
    return x


def q(data, uid=1):
    return {"id": "cb", "from": {"id": uid}, "data": data, "message": {"chat": {"id": 1}, "message_id": 9}}


def m(text="", **kw):
    return {"message_id": 3, "chat": {"id": 1}, "from": {"id": 1}, "text": text, **kw}


def texts(p):
    return [t for t, _ in p.sent]


def data_of(kw):
    return [b["callback_data"] for row in kw.get("reply_markup", {}).get("inline_keyboard", []) for b in row]


# ---------- кнопки под ответом окна ----------
def test_answer_buttons_act_on_their_window(p):
    p.on_callback(q("yes:@1"))
    assert p.got == [("@1", "да")]                                      # «✅ Да» — в окно ответа, не в активное
    p.on_callback(q("act:@1"))
    assert p.st["active"] == "@1" and "Пишу в «штаб»" in texts(p)[-1]
    p.on_callback(q("act:@33"))
    assert "свой Telegram-бот" in texts(p)[-1]                         # у окна свой канал — предупреждаем


def test_window_card_buttons(p, monkeypatch):
    p.on_callback(q("w:@1"))
    assert {"act:@1", "scr:@1", "last:@1", "ren:@1", "ask:@1"} <= set(data_of(p.sent[-1][1]))
    p.on_callback(q("scr:@1"))
    assert texts(p)[-1].startswith("[штаб] экран:") and "key:@1|1" in data_of(p.sent[-1][1])
    monkeypatch.setattr(transcripts, "last_answer", lambda *a: "")
    p.on_callback(q("last:@1"))
    assert "не нашёл" in texts(p)[-1]
    monkeypatch.setattr(transcripts, "last_answer", lambda *a: "последний ответ")
    p.on_callback(q("last:@1"))
    assert texts(p)[-1] == "последний ответ"
    p.on_callback(q(f"say:{p.counter}"))                               # 🔊 к нему — помнит, что читать
    p.on_callback(q("say:999"))
    assert "забыт" in texts(p)[-1]


def test_rename_flow_targets_the_pressed_window(p):
    p.on_callback(q("ren:@1"))
    assert p.waiting[1] == "ren:@1"
    p.on_message(m("главный штаб"))
    assert p.tmux.renamed == [("@1", "главный штаб")] and p.got == []   # имя — не текст для Claude
    p.on_callback(q("ren:@1"))
    p.on_message(m("   "))
    p.waiting[1] = "ren:@99"
    p.on_message(m("x"))
    assert "уже нет" in texts(p)[-1]


def test_close_paths(p, monkeypatch):
    monkeypatch.setattr(bot.focus.Focus, "end_window", lambda self, wid: None)
    p.on_callback(q("ask:@1"))
    assert data_of(p.sent[-1][1]) == ["close:@1", "noop:"]
    for res, want in (("background", "фоновые задачи"), ("busy", "не вышел")):
        monkeypatch.setattr(p, "quit_ex", lambda w, r=res: {"result": r, "draft": "черн"})
        p.on_callback(q("close:@1"))
        assert want in texts(p)[-1] and "черн" in texts(p)[-1]
        assert data_of(p.sent[-1][1]) == ["fclose:@1", "noop:"]         # можно закрыть принудительно
    p.on_callback(q("fclose:@1"))
    assert p.tmux.killed == ["@1"] and "принудительно" in texts(p)[-1]
    monkeypatch.setattr(p, "quit_ex", lambda w: {"result": "closed", "draft": ""})
    p.on_callback(q("close:@33"))
    assert texts(p)[-1] == "«штаб · 09:39» завершена."
    p.on_callback(q("close:@5"))                                       # терминал без Claude — просто закрыть
    assert "@5" in p.tmux.killed


def test_screen_keys_and_stop(p):
    p.on_callback(q("key:@1|Escape"))
    p.on_callback(q("key:@1|rm -rf"))                                  # не из списка клавиш — ничего
    assert p.tmux.keys_sent == [("@1", "Escape")]
    p.on_callback(q("key:@99|1"))
    assert "уже нет" in texts(p)[-1]
    p.on_callback(q("stop:@1"))
    assert data_of(p.sent[-1][1]) == ["key:@1|Escape", "noop:"]        # «Остановить» — только после «Да»


def test_gone_window_and_strangers(p):
    p.on_callback(q("yes:@77"))
    assert p.got == [] and "уже нет" in texts(p)[-1]
    n = len(p.sent)
    p.on_callback(q("yes:@1", uid=666))                                 # не владелец — кнопки не работают
    p.on_callback(q("noop:"))
    assert p.got == [] and len(p.sent) == n


def test_hint_button(p):
    p.hints[5] = ("@1", "запусти тесты")
    p.on_callback(q("hint:5"))
    assert p.got == [("@1", "запусти тесты")] and "→ [штаб]" in texts(p)[-1]
    p.on_callback(q("hint:6"))
    assert "устарела" in texts(p)[-1]


def test_commands_go_to_active_window(p, monkeypatch):
    slashed = []
    monkeypatch.setattr(p, "slash", lambda chat, w, cmd: slashed.append((w["id"], cmd)))
    p.cfg.commands = []
    names = [c for _, c in p.command_list()]
    p.on_callback(q(f"cmd:{names.index('/compact')}"))
    p.on_callback(q("cmd:/model opus"))
    assert slashed == [("@33", "/compact"), ("@33", "/model opus")]
    p.on_callback(q(f"cmd:{names.index('models')}"))
    assert "cmd:/model opus" in data_of(p.sent[-1][1])
    p.on_callback(q(f"cmd:{names.index('handoff')}"))
    assert p.got[-1][0] == "@33" and "HANDOFF" in p.got[-1][1]
    p.on_callback(q("cmd:999"))
    assert "устарела" in texts(p)[-1]
    p.st["active"] = "@5"                                              # активное — терминал без Claude
    p.on_callback(q("cmd:0"))
    assert "Активного окна с Claude нет" in texts(p)[-1]


def test_settings_buttons(p, monkeypatch):
    monkeypatch.setattr(p, "show_settings", lambda chat: p.sent.append(("настройки", {})))
    p.on_callback(q("set:notify=off"))
    p.on_callback(q("set:voice_always"))
    p.on_callback(q("set:notify=всё"))                                 # чужое значение — не пишем
    assert p.st["notify"] == "off" and p.st["voice_always"] is True


def test_new_session_buttons(p, monkeypatch):
    opened = []
    monkeypatch.setattr(p, "open_session", lambda chat, name, path, first=None: opened.append((name, path, first)))
    p.cfg.task_prompt = "Задача {task}"
    p.on_callback(q("new:1"))
    p.on_callback(q("tnew:2|GAS-7"))
    p.on_callback(q("new:9"))
    assert opened[0][1] == "/p/shtap" and opened[0][0].startswith("shtap-")
    assert opened[1] == (opened[1][0], "/p/x", "Задача GAS-7") and opened[1][0].startswith("gas-7-")
    assert "изменился" in texts(p)[-1]
    p.on_callback(q("mk:"))
    assert p.waiting[1] == "name"


# ---------- сообщения ----------
def test_menu_buttons(p, monkeypatch):
    p.changes = type("C", (), {"look": lambda self, wid, lines: None, "at": lambda self, wid: None})()
    monkeypatch.setattr(p, "stamps", lambda w: {"changed": None})
    p.on_message(m("🔀 Переключить"))
    assert set(data_of(p.sent[-1][1])) == {"act:@1", "act:@33"}        # только окна с Claude
    assert "✅ штаб · 09:39" in str(p.sent[-1][1])                      # активное — с галочкой
    p.on_message(m("📊 Сводка"))
    assert "терминал" in texts(p)[-1] and "▶️ штаб · 09:39" in texts(p)[-1]
    p.on_message(m("📋 Окна"))
    assert {"w:@1", "w:@33", "w:@5"} == set(data_of(p.sent[-1][1]))
    p.cfg.commands = []
    p.on_message(m("⚡ Команды"))
    assert "«штаб · 09:39»" in texts(p)[-1]
    p.on_message(m("🆕 Новая"))
    assert "mk:" in data_of(p.sent[-1][1]) and "new:1" in data_of(p.sent[-1][1])
    p.on_message(m("/help"))
    assert "активное окно" in texts(p)[-1]
    p.on_message(m("GAS-12"))
    assert "tnew:0|GAS-12" in data_of(p.sent[-1][1]) and p.got == []    # номер задачи — не текст для Claude


def test_empty_windows_lists(p):
    p.tmux.wins = []
    p.on_message(m("🔀"))
    p.on_message(m("📋"))
    p.on_message(m("📊"))
    assert "Окон с Claude нет" in texts(p)[0] and "Окон нет" in texts(p)[1] and "окон нет" in texts(p)[2]


def test_text_voice_file_and_sticker(p, monkeypatch, tmp_path):
    p.on_message(m("привет"))
    assert p.got[-1] == ("@33", "привет")
    p.api.download = lambda fid, d, name: tmp_path / name
    p.on_message(m("", caption="смотри", photo=[{"file_id": "a"}, {"file_id": "b"}]))
    assert p.got[-1][0] == "@33" and "смотри" in p.got[-1][1] and "photo.jpg" in p.got[-1][1]
    monkeypatch.setattr(bot.voice, "transcribe_any", lambda *a, **k: "голосом")
    p.cfg.whisper_model = "x"
    p.on_message(m("", voice={"file_id": "v"}))
    assert p.got[-1] == ("@33", "голосом") and "🎙 → [штаб · 09:39]: голосом" in texts(p)
    monkeypatch.setattr(bot.voice, "transcribe_any", lambda *a, **k: "")
    p.on_message(m("", voice={"file_id": "v"}))
    assert "Не разобрал" in texts(p)[-1]

    def boom(*a, **k):
        raise RuntimeError("нет модели")
    monkeypatch.setattr(bot.voice, "transcribe_any", boom)
    p.on_message(m("", voice={"file_id": "v"}))
    assert "нет модели" in texts(p)[-1]
    n = len(p.got)
    p.on_message(m("", sticker={"file_id": "s"}))
    assert len(p.got) == n and "Пришли текст" in texts(p)[-1]


def test_voice_reply_goes_to_replied_window(p, monkeypatch):
    monkeypatch.setattr(bot.voice, "transcribe_any", lambda *a, **k: "это для штаба")
    p.api.download = lambda fid, d, name: name
    p.cfg.whisper_model = "x"
    p.routes.bind(1, 50, "@1")
    p.on_message(m("", voice={"file_id": "v"}, reply_to_message={"message_id": 50, "from": {"is_bot": True}}))
    assert p.got == [("@1", "это для штаба")]


def test_no_active_window(p):
    p.st["active"] = ""
    p.on_message(m("кому?"))
    assert p.got == [] and "Активного окна с Claude нет" in texts(p)[-1]


# ---------- сводка (/digest) ----------
class Digest:
    def __init__(self, items):
        self.items, self.snoozed = {x["key"]: x for x in items}, []

    def fresh(self, items, now):
        return items

    def item(self, k):
        return self.items.get(k)

    def snooze(self, k, how):
        self.snoozed.append((k, how))


def test_digest_flow(p, monkeypatch):
    p.cfg.digest_github = []
    monkeypatch.setattr(bot.digest, "handoffs", lambda roots: [])
    p.tmux.screen_text = "Do you want to proceed?\n❯ 1. Yes\n  2. No"
    items = p.digest_items()
    assert [x["id"] for x in items] == ["@1", "@33"]                   # окна, которые ждут ответа
    p.digest = Digest([*items, {"kind": "handoff", "key": "h1", "path": "/p/shtap", "project": "shtap", "text": "PR?"},
                       {"kind": "pr", "key": "pr1", "repo": "o/r", "n": 7, "title": "T"}])
    p.send_digest(1)
    assert "dg:" in str(p.sent[-1][1])
    k1 = items[0]["key"]
    p.on_digest(1, f"y:{k1}")                                          # окно ждёт — экран этого окна
    assert texts(p)[-1].startswith("[штаб] Claude ждёт ответа:")
    p.on_digest(1, "y:h1")
    assert "dg:Y:h1" in str(p.sent[-1][1])                             # «да» — только с подтверждением
    monkeypatch.setattr(p, "project_window", lambda path: p.tmux.window("@1"))
    p.on_digest(1, "Y:h1")
    assert p.got[-1][0] == "@1" and "PR?" in p.got[-1][1] and ("h1", bot.digest.GONE) in p.digest.snoozed
    monkeypatch.setattr(p, "project_window", lambda path: None)
    p.on_digest(1, "Y:h1")
    assert "Окна с Claude" in texts(p)[-1]
    monkeypatch.setattr(bot.digest, "merge", lambda repo, n: f"слил {repo}#{n}")
    p.on_digest(1, "Y:pr1")
    assert texts(p)[-1] == "слил o/r#7"
    p.on_digest(1, "c:pr1")
    p.on_digest(1, "l:pr1")
    p.on_digest(1, "y:нет")
    assert "Убрал" in texts(p)[-3] and "Напомню" in texts(p)[-2] and "уже не в сводке" in texts(p)[-1]
    p.digest = Digest([])
    p.tmux.screen_text = PROMPT                                        # никто не ждёт
    p.send_digest(1)
    assert "Ничего не ждёт" in texts(p)[-1]
    p.on_callback(q("dg:c:x"))
    assert "уже не в сводке" in texts(p)[-1]


# ---------- мастер: вход в Claude Code ----------
class Login:
    def __init__(self, st=None, code=None):
        self.st, self.code, self.cancelled = st or {}, code, False

    def start(self):
        if isinstance(self.st, Exception):
            raise self.st
        return self.st

    def finish(self, st):
        return {"ok": True}

    def send_code(self, code):
        if isinstance(self.code, Exception):
            raise self.code
        return self.code

    def cancel(self):
        self.cancelled = True


def test_setup_wizard(p, monkeypatch):
    monkeypatch.setattr(p, "setup_status", lambda: {"claude": {"installed": True}, "ready": False})
    monkeypatch.setattr(bot.setup, "text", lambda st: "состояние")
    monkeypatch.setattr(p, "setup_kb", lambda st: {"inline_keyboard": []})
    p.show_setup(1)
    assert "вход не выполнен" in texts(p)[-1]
    p.show_setup(1, {"claude": {"installed": False}, "ready": False})
    assert "не установлен" in texts(p)[-1]
    p.show_setup(1, {"claude": {"installed": True}, "ready": True})
    assert "готов" in texts(p)[-1]
    p.login = Login({"url": "https://claude.ai/x"})
    p.on_setup(1, "login")
    assert p.waiting[1] == "code" and "https://claude.ai/x" in texts(p)[-1]
    p.login = Login(code={"ok": True})
    p.on_message(m("abc123"))                                          # ждём код — сообщение уходит в мастер
    assert "Вход в Claude выполнен" in texts(p)[-1] and p.got == []
    p.login = Login(code=ValueError("неверный код"))
    p.setup_code(1, "x")
    assert p.waiting[1] == "code" and "неверный код" in texts(p)[-1]
    p.login = Login(code=LookupError("окна входа нет"))
    p.setup_code(1, "x")
    assert "окна входа нет" in texts(p)[-1]
    p.setup_result(1, {"ok": False, "error": "истёк", "lines": ["экран"]})
    assert "истёк" in texts(p)[-1] and "экран" in texts(p)[-1]
    p.login = Login({"url": "", "lines": ["пусто"]})
    p.setup_login(1)
    assert "не показал ссылку" in texts(p)[-1]
    p.login = Login({"done": True})
    p.setup_login(1)
    assert "выполнен" in texts(p)[-1]
    p.login = Login(RuntimeError("tmux нет"))
    p.setup_login(1)
    assert "tmux нет" in texts(p)[-1]
    p.login = Login()
    p.on_setup(1, "cancel")
    assert p.login.cancelled and "отменён" in texts(p)[-1]
    p.on_setup(1, "int")
    p.on_setup(1, "keys")
    assert "Интеграции" in texts(p)[-2] and "COMPLIANCE" in texts(p)[-1]
    monkeypatch.setattr(p, "show_setup", lambda chat, st=None: p.sent.append(("мастер", {})))
    p.on_setup(1, "check")
    p.on_message(m("/setup"))
    assert texts(p)[-2:] == ["мастер", "мастер"]


def test_selftest_command(p, monkeypatch):
    monkeypatch.setattr(bot.selftest, "load", lambda data: {})
    monkeypatch.setattr(bot.selftest, "running", lambda d: True)
    p.on_message(m("/selftest"))
    assert "уже идёт" in texts(p)[-1]
    monkeypatch.setattr(bot.selftest, "running", lambda d: False)
    monkeypatch.setattr(bot.selftest, "run_all", lambda data, st: {})
    monkeypatch.setattr(bot.selftest, "summary", lambda data, st: "итог проверки")
    started = []
    monkeypatch.setattr(bot.threading, "Thread", lambda target, daemon: type("T", (), {
        "start": lambda self: started.append(target())})())
    p.on_message(m("/selftest"))
    assert "Проверяю" in texts(p)[-2] and texts(p)[-1] == "итог проверки"


def test_send_later_waits_until_ready(p, monkeypatch):
    calls = []

    def flaky(w, text, src=""):
        calls.append(w["id"])
        if len(calls) < 2:
            raise bot.NotReady("доверяете папке?")
    p.to_claude = flaky
    monkeypatch.setattr(bot.threading, "Thread", lambda target, daemon: type("T", (), {
        "start": lambda self: target()})())
    p.send_later("@1", "начинай", wait=60)
    assert calls == ["@1", "@1"]
    p.broadcast = lambda text, **kw: p.sent.append((text, kw))
    p.to_claude = lambda w, text, src="": (_ for _ in ()).throw(bot.NotReady("занято"))
    clock = iter(range(0, 1000, 30))
    monkeypatch.setattr(bot.time, "time", lambda: next(clock))
    p.send_later("@1", "начинай", wait=60)
    assert "не отправлено" in texts(p)[-1] and "занято" in texts(p)[-1]
    p.tmux.wins = []
    p.send_later("@1", "x")                                            # окна нет — молча выходим


# ---------- живая отправка: строка статуса, ключи в тексте, отказ ----------
def test_to_claude_live_names_window_hides_secret_and_cleans_up(p, monkeypatch):
    del p.to_claude_live                                               # настоящий метод класса
    p.send = lambda chat, text, **kw: p.sent.append((text, kw)) or {"message_id": 77}
    threads = []
    monkeypatch.setattr(bot.threading, "Thread", lambda target, args, daemon: type("T", (), {
        "start": lambda self: threads.append(args)})())
    p.to_claude_live(1, p.tmux.window("@1"), "ключ sk-ant-api03-" + "x" * 40 + " положи")
    assert "🔒" in texts(p)[0] and texts(p)[1].startswith("→ [штаб] ")   # куда ушло — видно
    assert p.got[-1][0] == "@1" and "sk-ant" not in p.got[-1][1]        # модель ключа не видела
    assert p.sent[1][1]["wid"] == "@1" and threads == [(1, 77, p.tmux.window("@1"))]   # reply на статус — сюда

    def fail(w, text, src=""):
        raise bot.NotReady("Claude ждёт ответа")
    p.to_claude = fail
    with pytest.raises(bot.NotReady):
        p.to_claude_live(1, p.tmux.window("@1"), "привет")
    assert ("deleteMessage", {"chat_id": 1, "message_id": 77}) in p.calls   # «⏳ Отправлено» не висит


def test_slash_command_goes_to_window(p, monkeypatch):
    from contextlib import nullcontext
    monkeypatch.setattr(p, "hold", lambda wid: nullcontext(), raising=False)
    monkeypatch.setattr(p, "ready_for_text", lambda wid: None, raising=False)
    monkeypatch.setattr(p, "stamps", lambda w: {"changed": None})
    lines = p.run_slash("@1", "/compact")
    assert p.tmux.typed == [("@1", "/compact")] and ("@1", "Enter") in p.tmux.keys_sent and lines
    p.slash(1, p.tmux.window("@1"), "/status")
    assert texts(p)[-1].startswith("[штаб] /status")


def test_rebind_keys_and_link_done(p, tmp_path, monkeypatch):
    f = p.cfg.data / "passkeys.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text('{"creds": {"c": {"uid": -5}}, "handles": {"-5": "h"}}')
    p.rebind_keys(-5, 42)
    d = __import__("json").loads(f.read_text())
    assert d["creds"]["c"]["uid"] == 42 and d["handles"] == {"42": "h"}
    f.write_text("[]")
    p.rebind_keys(-5, 42)                                              # не тот формат — не трогаем
    p.logins = type("L", (), {"info": lambda self, n: None, "decide": lambda self, *a: True})()
    p.link_done(1, {"id": 42}, "ok", "n")
    assert "устарела" in texts(p)[-1]


# ---------- маршрутизация служебных кнопок: каждая — в свой обработчик, чужим — только условия и страна ----------
def test_service_buttons_dispatch(p, monkeypatch):
    seen = []
    for name in ("grant", "budget_offer", "pick_space", "grant_space", "show_people", "switch_off", "on_digest",
                 "on_module", "offer_space", "term_open", "on_demo"):
        monkeypatch.setattr(p, name, lambda *a, n=name: seen.append(n), raising=False)
    monkeypatch.setattr(p, "budget_add", lambda chat, arg, uid: seen.append("budget_add"), raising=False)
    monkeypatch.setattr(p, "on_terms", lambda chat, uid, arg: seen.append(("terms", uid)), raising=False)
    monkeypatch.setattr(p, "on_country", lambda chat, uid, arg: seen.append(("country", uid)), raising=False)
    monkeypatch.setattr(p, "push_enter", lambda wid, h: f"Enter в {wid}:{h}", raising=False)
    monkeypatch.setattr(p, "ask_notify_done", lambda wid, chat: f"сообщу про {wid}", raising=False)
    for d in ("pp:1", "bt:x", "ba:x", "pt:x", "ps:x", "ppl:", "off:5", "dg:y:k", "md:x", "of:x", "tw:1", "twok:1"):
        p.on_callback(q(d))
    p.on_callback(q("dm:x", uid=666))                                   # демо — кому угодно
    p.on_callback(q("tm:1", uid=666))                                   # условия и страна — и не владельцу
    p.on_callback(q("cc:NL", uid=666))
    p.on_callback(q("pp:1", uid=666))                                   # остальное — нет
    assert seen == ["grant", "budget_offer", "budget_add", "pick_space", "grant_space", "show_people", "switch_off",
                    "on_digest", "on_module", "offer_space", "term_open", "term_open", "on_demo", ("terms", 666),
                    ("country", 666)]
    p.on_callback(q("rs:@1:abc"))
    p.on_callback(q("nd:@1"))
    assert texts(p)[-2:] == ["Enter в @1:abc", "сообщу про @1"]


def test_cost_and_setup_buttons(p, monkeypatch):
    monkeypatch.setattr(p, "cost_decide", lambda wid, act: f"{act} {wid}", raising=False)
    p.on_callback(q("cost:go:@1"))
    assert texts(p)[-1] == "go @1"

    def gone(wid, act):
        raise LookupError("продолжено")
    monkeypatch.setattr(p, "cost_decide", gone, raising=False)
    p.on_callback(q("cost:go:@1"))
    assert "Уже решено" in texts(p)[-1]
    p.people = type("P", (), {"role": lambda self, uid: "member"})()
    p.on_callback(q("su:login"))
    assert "только владелец" in texts(p)[-1]


def test_login_buttons(p):
    decided = []
    p.people = type("P", (), {"role": lambda self, uid: "member" if uid == 7 else None})()
    p.logins = type("L", (), {"decide": lambda self, n, uid, ok: decided.append((n, uid, ok)) or n != "old"})()
    p.on_callback(q("lg:ok:n1", uid=7))
    p.on_callback(q("lg:no:n2", uid=9))
    p.on_callback(q("lg:ok:n3", uid=9))                                 # без роли — не впускаем
    p.on_callback(q("lg:ok:old", uid=7))
    assert decided == [("n1", 7, True), ("n2", 9, False), ("old", 7, True)]
    assert "Вход подтверждён" in texts(p)[0] and "отклонён" in texts(p)[1] and "нет" in texts(p)[2]
    assert "устарела" in texts(p)[3]


def test_voice_buttons(p, monkeypatch):
    monkeypatch.setattr(bot.catalog, "label", lambda v: v.upper())
    p.cfg.personal_voices = False
    p.on_voice(1, "vi", "elevenlabs", {})
    p.on_voice(1, "vi", "irina", {})
    assert "ElevenLabs" in texts(p)[0] and "voices install irina" in texts(p)[1]

    def choose(v):
        raise ValueError("голос недоступен")
    monkeypatch.setattr(p, "choose_voice", choose, raising=False)
    p.on_voice(1, "vs", "x", {})
    assert texts(p)[-1] == "голос недоступен"
    monkeypatch.setattr(p, "voice_preview", lambda v, pers, ext: (b"ogg", "ogg"), raising=False)
    p.on_voice(1, "vp", "irina", {})
    assert p.calls[-1][0] == "sendVoice"
    p.st["audio_only"] = True
    monkeypatch.setattr(p, "voice_preview", lambda v, pers, ext: (b"mp3", ext), raising=False)
    p.on_voice(1, "vp", "irina", {})
    assert p.calls[-1][0] == "sendAudio"

    def bad(*a):
        raise RuntimeError("нет синтеза")
    monkeypatch.setattr(p, "voice_preview", bad, raising=False)
    p.on_voice(1, "vp", "irina", {})
    assert "нет синтеза" in texts(p)[-1]


def test_bot_commands_after_run_and_triage(p, monkeypatch):
    marks = []
    p.journal = type("J", (), {"collect": lambda self, w, k: None,
                               "flag_cmd": lambda self, *a, **k: marks.append("run"),
                               "mark_cmd": lambda self, path, cmd, rec, out: marks.append(rec["triage"]),
                               "triage_once": lambda self, key: True, "forget_triage": lambda self, key: None})()
    p.cmds = type("C", (), {"kind": lambda self, *a: "", "offer": lambda *a: None})()
    p.before_run("make", "/p/shtap")
    assert p.after_run("make", "/p/shtap", 0, 1.0, "ok") == ""
    note = p.after_run("make", "/p/shtap", 2, 1.0, "boom")
    assert marks == ["run", "", "sent"] and "[штаб]" in note and p.got[-1][0] == "@1"   # упала — на разбор в окно
    assert p.after_run("make", "/p/none", 2, 1.0, "boom") == bot.TRIAGE_NOTE["closed"]


# ---------- фоновые циклы бота: одна итерация ----------
class Stop(Exception):
    pass


def test_poll_loop_handles_only_admitted_updates(p, monkeypatch):
    batches = [[{"update_id": 5, "message": m("свой")}, {"update_id": 6, "message": {**m("чужой"), "from": {"id": 9}}}]]

    def api(method, **kw):
        if method == "getMe":
            return {"username": "b"}
        if method == "getUpdates":
            if batches:
                return batches.pop()
            raise Stop
        return {}
    p.api = api
    p.api.redact = str
    monkeypatch.setattr(p, "setup_status", lambda: {"ready": False, "claude": {"installed": False}})
    handled = []
    monkeypatch.setattr(p, "admitted", lambda u: u["message"]["from"]["id"] == 1)
    monkeypatch.setattr(bot.threading, "Thread", lambda target, daemon, args=(): type("T", (), {
        "start": lambda self: handled.append(args[0]["update_id"]) if args else None})())
    monkeypatch.setattr(bot.time, "sleep", lambda s: (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        p.run()
    assert handled == [5]                                              # чужих — молча


def test_handle_reports_errors_to_the_chat(p, monkeypatch):
    p.api = type("A", (), {"redact": staticmethod(str), "__call__": lambda self, *a, **k: {}})()
    monkeypatch.setattr(p, "need_terms", lambda u: False)
    monkeypatch.setattr(p, "need_country", lambda u: False)

    def boom(msg):
        raise RuntimeError("tmux упал")
    monkeypatch.setattr(p, "on_message", boom)
    p.handle({"message": m("x")})
    assert texts(p)[-1] == "Ошибка: tmux упал"

    def deny(msg):
        raise bot.Denied("не для вашей страны")
    monkeypatch.setattr(p, "on_message", deny)
    p.handle({"message": m("x")})
    assert texts(p)[-1] == "не для вашей страны"


def test_digest_and_selftest_loops_one_round(p, monkeypatch):
    p.api = type("A", (), {"redact": staticmethod(str)})()
    sent = []
    p.digest = type("D", (), {"due": lambda self, at, now: True, "mark_sent": lambda self, d: sent.append("mark")})()
    p.cfg.digest_at = "09:00"
    monkeypatch.setattr(p, "send_digest", lambda chat=None: sent.append("digest"))
    monkeypatch.setattr(p, "send_testers", lambda chat=None: sent.append("testers"), raising=False)
    monkeypatch.setattr(bot.features, "due", lambda data, now: True)
    monkeypatch.setattr(bot.features, "mark_sent", lambda data, now: sent.append("fmark"))
    monkeypatch.setattr(p, "send_features", lambda now: sent.append("features"))
    monkeypatch.setattr(bot.time, "sleep", lambda s: (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        p.digest_loop()
    assert sent == ["mark", "digest", "testers", "fmark", "features"]
    naps = []

    def nap(s):                                                        # первый sleep — 300 с после запуска
        naps.append(s)
        if len(naps) > 1:
            raise Stop
    monkeypatch.setattr(bot.time, "sleep", nap)
    monkeypatch.setattr(bot.selftest, "due", lambda data, st: True)
    monkeypatch.setattr(bot.selftest, "run_all", lambda data, st: {"results": {"zai": {"checks": {"ok": False}}}})
    monkeypatch.setattr(bot.selftest, "summary", lambda data, st: "zai не прошёл")
    p.broadcast = lambda text, **kw: sent.append(text)
    with pytest.raises(Stop):
        p.selftest_loop()
    assert sent[-1] == "zai не прошёл"


def test_wait_ready_modules_loop_and_dialog_edit(p, monkeypatch):
    p.tmux.screen_text = "загрузка…"
    assert p.wait_ready("@1", limit=2) is False
    p.tmux.screen_text = PROMPT
    assert p.wait_ready("@1", limit=2) is True
    p.api = type("A", (), {"redact": staticmethod(str)})()
    monkeypatch.setattr(p, "module_tick", lambda now: (_ for _ in ()).throw(RuntimeError("модуль")))
    monkeypatch.setattr(bot.time, "sleep", lambda s: (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        p.modules_loop()                                               # ошибка модуля не роняет цикл
    # открытое меню Claude — одно сообщение каждому владельцу, изменилось — правим его же
    edits = []
    p.api = lambda method, **kw: edits.append(method) or {}
    p.send = lambda chat, text, wid=None, **kw: {"message_id": 41}
    shown = {}
    p.tmux.screen_text = "Do you want to proceed?\n❯ 1. Yes"
    w = p.tmux.window("@1")
    p.show_dialog(w, p.tmux.screen_text, shown)
    assert shown["@1"]["msgs"] == {1: 41}
    shown["@1"]["t"] -= 10
    p.show_dialog(w, "Do you want to proceed?\n❯ 2. No", shown)
    assert edits == ["editMessageText"]


def test_broadcast_survives_telegram_error(p):
    p.cfg.owners = [1, 2]

    def send(chat, text, **kw):
        if chat == 1:
            raise bot.TelegramError("sendMessage", "chat not found")
        p.sent.append((text, {"chat": chat}))
    p.send = send
    p.broadcast("всем")
    assert p.sent == [("всем", {"chat": 2})]                           # ошибка у одного — остальным дошло
