"""Живая строка статуса (#71) — добавки итерации 1: анти-мигание в панели (фаза держится не меньше 900 мс, меняется
только textContent, таймер — tabular-nums), бот правит сообщение не чаще раза в 3,5 с, эскалация по времени без
нового хода и смены фазы 12/20/60 с: «Проверить статус», «Сообщить по готовности», «Остановить» (Esc, с «Да»)."""

import json
import re
import threading
from pathlib import Path

import pytest

from gas_pult import bot
from gas_pult.config import Config

INDEX = (Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html").read_text(encoding="utf-8")


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def follower(states, clock):
    """Pult без __init__: activity() отдаёт фазы по очереди, api() копит правки."""
    p = bot.Pult.__new__(bot.Pult)
    p.lock, p.following, p.pause_until, p.calls = threading.Lock(), {}, 0.0, []
    seq = iter(states)
    p.api = lambda method, **kw: p.calls.append((method, kw)) or {"message_id": 5}
    p.activity = lambda w: next(seq)
    return p


def run(p, clock):
    sleeps = []

    def sleep(sec):
        sleeps.append(sec)
        clock.t += sec
    p.follow(1, 5, {"id": "@1", "name": "shop"}, clock=clock, sleep=sleep)
    return sleeps


def rows(kw) -> list[str]:
    return [b["callback_data"] for r in (kw.get("reply_markup") or {}).get("inline_keyboard", []) for b in r]


def test_bot_throttles_edits_to_3_5_seconds():
    clock = Clock()
    st = [{"phase": "working", "text": f"Читает файл {i}.py", "since": clock.t} for i in range(6)]
    p = follower([*st, {"phase": "done", "text": "", "since": clock.t}], clock)
    sleeps = run(p, clock)
    assert bot.Pult.FOLLOW_EVERY == 3.5 and all(s >= 3.5 for s in sleeps)
    edits = [c for c in p.calls if c[0] == "editMessageText"]
    assert len(edits) <= len(sleeps)                         # не больше одной правки за 3,5 с


def test_bot_escalates_12_20_60_without_progress():
    clock = Clock()
    same = {"phase": "working", "text": "Выполняет команду: npm test", "since": clock.t}
    p = follower([same] * 20 + [{"phase": "done", "text": "", "since": clock.t}], clock)
    run(p, clock)
    marks = [rows(kw) for m, kw in p.calls if m == "editMessageText"]
    seen = [len(r) for r in marks]
    assert 1 in seen and 2 in seen and 3 in seen, seen       # 12 с — 1 кнопка, 20 с — 2, 60 с — 3
    full = next(r for r in marks if len(r) == 3)
    assert full == ["scr:@1", "nd:@1", "stop:@1"]
    assert rows(p.calls[-1][1]) == []                        # «Готово» — без кнопок


def test_bot_progress_resets_escalation():
    clock = Clock()
    st = [{"phase": "working", "text": f"Шаг {i // 3}", "since": clock.t} for i in range(18)]
    p = follower([*st, {"phase": "done", "text": "", "since": clock.t}], clock)
    run(p, clock)                                            # шаг меняется каждые 10,5 с — до 12 с не доходит
    assert all(rows(kw) == [] for m, kw in p.calls if m == "editMessageText")


@pytest.fixture
def pult(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    p = bot.Pult(Config(token="1:T", owners=[1], project_roots=[str(tmp_path / "projects")]))
    p.sent = []
    p.send = lambda chat, text, **kw: p.sent.append((chat, text, kw))
    p.notify = lambda uid, text: p.sent.append((uid, text, {}))
    p.api = lambda method, **kw: {}
    return p


def test_stop_asks_before_esc(pult):
    p = pult
    p.tmux = type("T", (), {"window": lambda self, wid: {"id": wid, "name": "shop", "path": "/x", "channel": False}})()
    p.on_callback({"id": "q", "from": {"id": 1}, "message": {"chat": {"id": 1}}, "data": "stop:@1"})
    _, text, kw = p.sent[-1]
    assert "Остановить" in text and "key:@1|Escape" in json.dumps(kw) and "noop:" in json.dumps(kw)
    p.on_callback({"id": "q", "from": {"id": 9}, "message": {"chat": {"id": 9}}, "data": "stop:@1"})
    assert p.sent[-1][0] == 1                                # чужим — ничего


def test_notify_when_turn_ends_once(pult):
    p = pult
    ws = [{"id": "@1", "name": "shop"}]
    assert "пришлю" in p.ask_notify_done("@1", 2)
    p.on_callback({"id": "q", "from": {"id": 1}, "message": {"chat": {"id": 1}}, "data": "nd:@1"})
    assert p.state()["notify_done"]["@1"]["to"] == [1, 2]
    p.notify_done_check(ws, {"@1": "❯ "}, p.state())          # ещё не видели «занят» — ждём
    assert not [x for x in p.sent if "🔔" in x[1]]
    p.notify_done_check(ws, {"@1": "✻ Working… (esc to interrupt)"}, p.state())
    assert not [x for x in p.sent if "🔔" in x[1]]
    p.notify_done_check(ws, {"@1": "❯ "}, p.state())          # освободился — одно сообщение каждому
    said = [x for x in p.sent if "🔔" in x[1]]
    assert sorted(c for c, *_ in said) == [1, 2] and "ход закончен" in said[0][1]
    p.notify_done_check(ws, {"@1": "❯ "}, p.state())
    assert len([x for x in p.sent if "🔔" in x[1]]) == 2      # без повторов
    p.ask_notify_done("@1", 1)
    p.notify_done_check([], {}, p.state())                   # окна нет — забыли молча
    assert p.state()["notify_done"] == {}


def test_panel_anti_flicker_and_escalation_in_page():
    assert re.search(r"const ACT_DWELL = 900, ACT_ESC = \[12, 20, 60\]", INDEX)
    assert "font-variant-numeric: tabular-nums" in INDEX[INDEX.index(".act .tm"):][:200]
    for label in ("Проверить статус", "Сообщить по готовности", "Остановить"):
        assert label in INDEX
    assert '"/api/notify-done"' in INDEX and 'key: "Escape"' in INDEX
    paint = INDEX[INDEX.index("function paintAct()"):INDEX.index("function paintActTimer()")]
    assert "innerHTML" not in paint.split("const btn")[0]    # текст строки — только textContent
