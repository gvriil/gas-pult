"""Лимит Telegram (429): бот молчит сколько сказано и потом шлёт одно сообщение вместо пропущенных."""

import pytest

from gas_pult import bot
from gas_pult.telegram import TelegramError


def make(monkeypatch, clock):
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = type("C", (), {"owners": [1]})()
    p.calls = []

    def api(method, **kw):
        p.calls.append(kw.get("text", ""))
        if len(p.calls) == 1:
            raise TelegramError("sendMessage", "Too Many Requests: retry after 13", 13)
        return {"message_id": len(p.calls)}

    p.api = api
    monkeypatch.setattr(bot.time, "time", lambda: clock[0])
    return p


def test_429_pauses_sending_and_reports_once(monkeypatch):
    clock = [1000.0]
    p = make(monkeypatch, clock)
    with pytest.raises(TelegramError):
        p.send(1, "первое")                                  # Telegram: 429, молчать 13 с
    for _ in range(50):                                      # монитор пытается дальше — в Telegram не уходит ничего
        p.broadcast("ещё")
    assert p.calls == ["первое"]
    p.after_pause()                                          # пауза не кончилась — сводки нет
    assert p.calls == ["первое"]
    clock[0] += 14
    p.after_pause()
    p.after_pause()
    assert len(p.calls) == 2 and "51 уведомл." in p.calls[1]  # одно сообщение вместо 51
