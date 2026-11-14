"""Автоархив (#189 п. 12): сессии без активности N дней закрываются сами; по умолчанию — никогда."""

import time

from gas_pult import bot
from gas_pult.config import Config

DAY = 86400


class Wins:
    def __init__(self, wins, busy=()):
        self.wins, self.busy, self.killed = wins, set(busy), []

    def windows(self):
        return [dict(w) for w in self.wins]

    def screen(self, wid, n=25):
        return ["esc to interrupt"] if wid in self.busy else ["❯ "]

    def kill(self, wid):
        self.killed.append(wid)


def make(tmp_path, monkeypatch, days, wins, changed, busy=(), quit_result="closed"):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = Config(token="t", owners=[1], auto_close_days=days)
    p.tmux = Wins(wins, busy)
    p.state = lambda: {"active": "@1"}
    p.stamps = lambda w: {"changed": changed.get(w["id"])}
    p.quits, p.sent = [], []
    p.quit_ex = lambda w: p.quits.append(w["id"]) or {"result": quit_result, "draft": ""}
    p.broadcast = lambda text, **kw: p.sent.append(text)
    return p


def w(i, **kw):
    return {"id": f"@{i}", "name": f"s{i}", "cmd": "claude", "path": "/p", **kw}


def test_default_never(tmp_path, monkeypatch):
    p = make(tmp_path, monkeypatch, 0, [w(2)], {"@2": 1.0})
    assert p.auto_close_tick() == [] and p.quits == []


def test_closes_only_old_free_not_active_not_space(tmp_path, monkeypatch):
    now = time.time()
    wins = [w(1), w(2), w(3), w(4, space="demo"), w(5, stopped=True, cmd="bash"), w(6, sleep=True), w(7), w(8)]
    old, new = now - 8 * DAY, now - DAY
    changed = {"@1": old, "@2": old, "@3": new, "@4": old, "@5": old, "@6": old, "@7": old}   # @8 — неизвестно
    p = make(tmp_path, monkeypatch, 7, wins, changed, busy={"@7"})
    closed = p.auto_close_tick(now)
    assert closed == ["s2", "s5", "s6"]
    assert p.quits == ["@2"] and p.tmux.killed == ["@5", "@6"]          # спящее и остановленное — просто закрыть
    assert "s2, s5, s6" in p.sent[0] and "Продолжить" in p.sent[0]
    assert p.auto_close_tick(now + 60) == []                             # не чаще раза в 10 минут


def test_background_tasks_keep_window(tmp_path, monkeypatch):
    now = time.time()
    p = make(tmp_path, monkeypatch, 3, [w(2)], {"@2": now - 9 * DAY}, quit_result="background")
    assert p.auto_close_tick(now) == [] and p.sent == []


def test_config_example_documents_setting():
    from pathlib import Path
    ex = (Path(__file__).resolve().parents[1] / "config.example.toml").read_text()
    assert "auto_close_days = 0" in ex
