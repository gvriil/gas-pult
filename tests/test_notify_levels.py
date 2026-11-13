"""Уровень уведомлений на сессию (#189 п. 1, #177): «все», «только вопросы и ошибки», «тихо»; своё уведомление
агента — ``gas-pult notify``. Было: один режим на все окна — шумная сессия забивала Telegram, тихую нельзя было
оставить только с вопросами."""

import json
from pathlib import Path

import pytest
from test_project_chats import call
from test_project_chats import server as server

from gas_pult import bot, cli, notifylevel, tgroutes, transcripts
from gas_pult.config import Config

INDEX = (Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html").read_text(encoding="utf-8")


def test_levels_and_fallback_to_global_mode():
    st = {"notify": "all", "active": "@1"}
    assert notifylevel.level(st, "@2") == "all"
    assert notifylevel.level({**st, "notify": "off"}, "@2") == "muted"
    assert notifylevel.level({**st, "notify": "active"}, "@1") == "all"
    assert notifylevel.level({**st, "notify": "active"}, "@2") == "muted"
    st["notify_levels"] = notifylevel.updated(st, "@2", "input")
    assert notifylevel.wants(st, "@2", "dialog") and notifylevel.wants(st, "@2", "error")
    assert not notifylevel.wants(st, "@2", "answer")
    st["notify_levels"] = notifylevel.updated(st, "@2", "muted")
    assert not notifylevel.wants(st, "@2", "dialog")
    st["notify_levels"] = notifylevel.updated(st, "@2", "inherit")
    assert notifylevel.own(st, "@2") is None and notifylevel.level(st, "@2") == "all"
    with pytest.raises(ValueError):
        notifylevel.updated(st, "@2", "громко")
    st["notify_levels"] = {"@2": "input", "@3": "мусор"}
    assert notifylevel.moved(st, "@2", "@9") == {"@9": "input", "@3": "мусор"}
    assert notifylevel.level(st, "@3") == "all"                         # битое значение — как общий режим


class Wins:
    def __init__(self):
        self.wins = [{"id": "@1", "name": "a", "cmd": "claude", "path": "/p/a", "sid": "", "channel": False},
                     {"id": "@2", "name": "b", "cmd": "claude", "path": "/p/b", "sid": "", "channel": False}]

    def windows(self):
        return [dict(w) for w in self.wins]

    def window(self, wid):
        return next((dict(w) for w in self.wins if w["id"] == wid), None)

    def screen(self, wid, n=25):
        return ["Do you want to proceed?", "❯ 1. Yes"]

    def hint(self, wid):
        return ""


def test_monitor_respects_levels(tmp_path, monkeypatch):
    """Ответ окна «только вопросы» не приходит, его вопрос — приходит; «тихо» — ничего."""
    p = bot.Pult.__new__(bot.Pult)
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    p.cfg = Config(token="t", owners=[1])
    p.tmux = Wins()
    st = {"notify": "all", "voice_always": False, "notify_levels": {"@1": "input", "@2": "muted"}}
    p.state = lambda: dict(st)
    p.api = type("A", (), {"redact": staticmethod(str)})()
    delivered, dialogs = [], []
    p.deliver = lambda w, text: delivered.append(w["id"])
    p.show_dialog = lambda w, scr, shown: dialogs.append(w["id"])
    p.home_of = lambda w: None
    p.fallback = type("F", (), {"seen": lambda *a: None, "pending": {}})()
    p.changes = type("C", (), {"look": lambda *a: None})()
    for name in ("draft_watch", "notify_done_check", "offer_hints", "cost_watch", "after_pause"):
        setattr(p, name, lambda *a, **k: None)
    monkeypatch.setattr(transcripts, "transcripts", lambda path, home: [Path(path)])

    class Tail:
        def __init__(self, t):
            pass

        def watch(self, key, files):
            pass

        def read(self, f):
            return [{"x": f}]
    monkeypatch.setattr(transcripts, "Tail", Tail)
    monkeypatch.setattr(transcripts, "Turns", lambda: type("T", (), {"feed": lambda self, e: "ответ"})())

    class Stop(Exception):
        pass
    monkeypatch.setattr(bot.time, "sleep", lambda s: (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        p.monitor()
    assert delivered == [] and dialogs == ["@1"]
    st["notify_levels"] = {}
    with pytest.raises(Stop):
        p.monitor()
    assert delivered == ["@1", "@2"]                                    # без своих уровней — как раньше


def test_bot_buttons_set_level(tmp_path, monkeypatch):
    p = bot.Pult.__new__(bot.Pult)
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    p.cfg = Config(token="t", owners=[1])
    p.tmux = Wins()
    st = {"notify": "all"}
    p.state, p.set_state = (lambda: dict(st)), (lambda **kw: st.update(kw))
    sent = []
    p.to = lambda chat: lambda text, **kw: sent.append((text, kw))
    p.api = lambda *a, **k: {}
    q = {"id": "c", "from": {"id": 1}, "message": {"chat": {"id": 1}}}
    p.on_callback({**q, "data": "w:@1"})
    assert "nl:@1|input" in json.dumps(sent[-1][1]) and "Уведомления: все" in sent[-1][0]
    p.on_callback({**q, "data": "nl:@1|input"})
    assert st["notify_levels"] == {"@1": "input"} and "только вопросы" in sent[-1][0]
    p.on_callback({**q, "data": "nl:@1|громко"})
    p.on_callback({**q, "data": "nl:@7|all"})
    assert "уровень" in sent[-2][0] and "уже нет" in sent[-1][0]


def test_panel_api(server, monkeypatch):
    p, base, *_ = server
    state = {"notify": "all"}
    monkeypatch.setattr(p.pult, "state", lambda: dict(state))
    monkeypatch.setattr(p.pult, "set_state", lambda **kw: state.update(kw))
    tok = p.auth.issue(1)
    code, d = call(base, "/api/notify/level", {"w": "@1", "level": "input"}, tok)
    assert code == 200 and d == {"notify": "input"} and state["notify_levels"] == {"@1": "input"}
    s = next(x for x in call(base, "/api/sessions", tok=tok)[1]["sessions"] if x["id"] == "@1")
    assert s["notify"] == "input" and s["notify_own"] is True
    assert call(base, "/api/notify/level", {"w": "@1", "level": "all"}, p.auth.issue(2))[0] == 403   # участнику — нет
    assert call(base, "/api/notify/level", {"w": "@1", "level": "x"}, tok)[0] == 400


def test_cli_notify_binds_reply_to_own_window(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(cli.config, "load", lambda: Config(token="t", owners=[1, 2]))
    calls = []

    class Api:
        def __init__(self, token):
            pass

        def __call__(self, method, **kw):
            calls.append(kw)
            if kw["chat_id"] == 2:
                raise cli.TelegramError("sendMessage", "chat not found")
            return {"message_id": 55}

        def redact(self, e):
            return str(e)
    monkeypatch.setattr(cli, "Api", Api)
    monkeypatch.setattr(cli, "own_window", lambda: ("@4", "штаб"))
    cli.main(["notify", "Готово,", "посмотрите"])
    assert calls[0]["text"] == "🔔 [штаб] Готово, посмотрите"
    assert tgroutes.Routes(tmp_path / "tg_routes.json").get(1, 55) == "@4"   # reply — в окно агента
    assert "отправлено владельцам: 1" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        monkeypatch.setattr(cli.sys, "stdin", type("S", (), {"isatty": lambda self: True})())
        cli.main(["notify"])


def test_own_window_outside_tmux(monkeypatch):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    assert cli.own_window() == ("", "")


def test_ui_has_notify_sheet():
    assert "function notifySheet(s)" in INDEX and '"/api/notify/level"' in INDEX and "Как в настройках бота" in INDEX
