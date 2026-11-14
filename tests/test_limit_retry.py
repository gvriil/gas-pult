"""Один отложенный повтор после лимита подписки (#189 п. 6): повторы не копятся, новое сообщение обгоняет повтор."""

import time
from datetime import datetime

import pytest

from gas_pult import bot, fallback, limitretry
from gas_pult.config import Config

NOW = datetime(2026, 11, 14, 12, 0).timestamp()


def test_reset_from_snapshot_and_text():
    lim = {"limits": {"five_hour": {"used": 100, "resets_at": NOW + 3600},
                      "seven_day": {"used": 40, "resets_at": NOW + 9e5}}}
    assert limitretry.reset_at("", lim, NOW) == NOW + 3600                # исчерпан 5-часовой — его сброс
    assert limitretry.reset_at(f"Claude AI usage limit reached|{int(NOW + 7200)}", None, NOW) == NOW + 7200
    t = limitretry.reset_at("5-hour limit reached ∙ resets 3pm", None, NOW)
    assert datetime.fromtimestamp(t).hour == 15 and t > NOW
    t = limitretry.reset_at("You've hit your limit · resets 11am (Europe/Amsterdam)", None, NOW)
    assert datetime.fromtimestamp(t).day == 15                            # 11:00 уже прошло — завтра
    assert limitretry.reset_at("resets 25:99", None, NOW) is None
    assert limitretry.reset_at("ничего", {"limits": {"five_hour": {"used": 50, "resets_at": NOW + 1}}}, NOW) is None


def test_one_retry_per_window():
    st = {}
    for i in range(5):                                                    # пять отказов подряд — запись одна
        st["limit_retries"] = limitretry.schedule(st, "@1", "штаб", NOW + 100 + i, NOW)
    assert list(st["limit_retries"]) == ["@1"] and st["limit_retries"]["@1"]["at"] == NOW + 104 + limitretry.SLACK
    assert limitretry.due(st, NOW) == [] and limitretry.due(st, NOW + 1000)[0][0] == "@1"
    assert limitretry.cancel(st, "@1") == {}


def test_switcher_calls_on_rate_when_no_fallback():
    calls = []
    sw = fallback.Switcher(None, lambda: {"fallback_chain": ["claude"]}, "claude", say=lambda line: None,
                           keys=lambda: {}, on_rate=lambda w, text: calls.append((w["id"], text)))
    e = {"type": "assistant", "isApiErrorMessage": True, "error": "rate_limit", "timestamp": None,
         "message": {"content": [{"type": "text", "text": "Claude AI usage limit reached|1794600000"}]}}
    sw.seen("@1", e)
    sw.step({"id": "@1", "name": "штаб", "path": "/p", "profile": "claude"}, idle=True)
    assert calls == [("@1", "Claude AI usage limit reached|1794600000")]
    sw.on_rate, calls[:] = (lambda w, text: calls.append(1)), []
    sw.act({"id": "@2", "name": "x", "path": "/p", "profile": "claude"}, "server", 503)
    assert calls == []                                                    # сбой сервера — не лимит, повтор не ставим


class Deliv:
    def __init__(self, rows):
        self.rows = rows

    def recent(self, within=3600):
        return self.rows

    def record(self, *a, **k):
        pass


@pytest.fixture
def p(tmp_path, monkeypatch):
    x = bot.Pult.__new__(bot.Pult)
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    x.cfg = Config(token="t", owners=[1])
    st = {}
    x.state, x.set_state = (lambda: dict(st)), (lambda **kw: st.update(kw))
    x.st, x.sent, x.got = st, [], []
    x.broadcast = lambda text, **kw: x.sent.append((text, kw))
    x.to_claude = lambda w, text, src="": x.got.append((w["id"], text))
    x.deliv = Deliv([])
    return x


def test_limit_wait_schedules_and_tells(p, monkeypatch):
    monkeypatch.setattr(bot.ctxsnap, "limits", lambda: {"limits": {"five_hour": {"used": 100,
                                                                                 "resets_at": time.time() + 1800}}})
    p.limit_wait({"id": "@1", "name": "штаб"}, "usage limit")
    assert "@1" in p.st["limit_retries"] and "Продолжу сама" in p.sent[-1][0]
    assert "rc:@1" in str(p.sent[-1][1])                                  # кнопка «Не продолжать»
    monkeypatch.setattr(bot.ctxsnap, "limits", lambda: {"limits": {"seven_day": {"used": 100,
                                                                                 "resets_at": time.time() + 9 * 3600}}})
    p.limit_wait({"id": "@2", "name": "b"}, "")
    assert "@2" not in p.st["limit_retries"] and "дольше 6 часов" in p.sent[-1][0]
    monkeypatch.setattr(bot.ctxsnap, "limits", lambda: None)
    p.limit_wait({"id": "@3", "name": "c"}, "лимит")
    assert "не знаю" in p.sent[-1][0]


def test_retry_tick_continues_or_is_overtaken(p):
    w1, w2, w3 = ({"id": f"@{i}", "name": f"s{i}"} for i in (1, 2, 3))
    old = time.time() - 100
    p.st["limit_retries"] = {"@1": {"at": old, "since": old - 50, "name": "s1"},
                             "@2": {"at": old, "since": old - 50, "name": "s2"},
                             "@3": {"at": old, "since": old - 50, "name": "s3"},
                             "@9": {"at": old, "since": old - 50, "name": "gone"},
                             "@4": {"at": time.time() + 999, "since": old, "name": "later"}}
    p.deliv = Deliv([{"w": "@2", "src": "panel", "ts": old}])           # в @2 человек уже написал сам
    p.retry_tick([w1, w2, w3], {"@3": "esc to interrupt"}, p.st)
    assert p.got == [(w1["id"], limitretry.TEXT)]                        # @1 — продолжили
    assert set(p.st["limit_retries"]) == {"@3", "@4"}                    # @3 занята — ждёт; @4 — не пора
    assert "лимит подписки обновился" in p.sent[-1][0]


def test_cancel_button(p):
    p.st["limit_retries"] = {"@1": {"at": 1, "since": 0}}
    out = []
    p.to = lambda chat: lambda text, **kw: out.append(text)
    p.api = lambda *a, **k: {}
    p.on_callback({"id": "c", "from": {"id": 1}, "message": {"chat": {"id": 1}}, "data": "rc:@1"})
    assert p.st["limit_retries"] == {} and "не продолжу" in out[-1]
