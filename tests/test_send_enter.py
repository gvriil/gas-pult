"""Текст из панели или бота не остаётся висеть в поле ввода Claude Code: после Enter пульт смотрит поле ввода и, если
там всё ещё наш текст, жмёт Enter ещё раз; не ушёл и после повторов — честно «не отправлено», а не «Доставлено».
Регрессия 09.11: текст владельца висел в поле ввода штаба неотправленным, пока его не отправили руками."""

import pytest

from gas_pult import bot, tmux

TEXT = "NORVEX скрыть, focus-projects оформить PR, остальные скрыть"


class FakeTmux(tmux.Tmux):
    def __init__(self, drafts):
        super().__init__("main")
        self.drafts, self.calls = list(drafts), []

    def run(self, *a, **k):
        self.calls.append(a)
        return ""

    def draft(self, wid):
        return self.drafts.pop(0) if self.drafts else ""


def enters(t):
    return sum(1 for c in t.calls if c[:1] == ("send-keys",) and c[-1] == "Enter")


def test_sent_first_time_one_enter():
    t = FakeTmux([""])
    assert t.paste("@1", TEXT, sleep=lambda s: None) is True
    assert enters(t) == 1


def test_lost_enter_is_repeated():
    t = FakeTmux([TEXT, ""])                       # первый Enter потерялся — текст ещё в поле
    assert t.paste("@1", TEXT, sleep=lambda s: None) is True
    assert enters(t) == 2


def test_collapsed_paste_counts_as_ours():
    t = FakeTmux(["[Pasted text #1 +12 lines]", "[Pasted text #1 +12 lines]", ""])
    assert t.paste("@1", "строка\n" * 12, sleep=lambda s: None) is True
    assert enters(t) == 3


def test_stuck_reports_not_sent():
    t = FakeTmux([TEXT] * 10)
    assert t.paste("@1", TEXT, sleep=lambda s: None) is False
    assert enters(t) == 4                          # первый + три повтора, дальше не жмём


def test_someone_elses_draft_untouched():
    t = FakeTmux(["человек печатает своё"])          # не наш текст — лишний Enter не жмём
    assert t.paste("@1", TEXT, sleep=lambda s: None) is True
    assert enters(t) == 1


def test_is_ours():
    assert tmux.is_ours("NORVEX скрыть,\nfocus-projects", TEXT)
    assert tmux.is_ours("[Pasted text #2 +40 lines]", "x")
    assert not tmux.is_ours("другое", TEXT) and not tmux.is_ours("", TEXT)


def test_to_claude_raises_when_text_stuck(monkeypatch, tmp_path):
    p = bot.Pult.__new__(bot.Pult)
    p.locks, p.actor = tmp_path / "locks", None

    class T:
        def paste(self, wid, text):
            return False
    p.tmux = T()
    monkeypatch.setattr(p, "cost_paused", lambda wid: False, raising=False)
    monkeypatch.setattr(p, "ready_for_text", lambda wid: None, raising=False)
    with pytest.raises(bot.NotReady, match="не отправлен"):
        p.to_claude({"id": "@1", "profile": "claude"}, TEXT)
