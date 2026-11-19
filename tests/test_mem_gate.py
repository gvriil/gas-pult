"""Пропуск новой сессии по памяти (GAS-25 п.1; зависание сервера 18.11, GAS-22): свободной памяти меньше порога и
после усыпления простаивающих — новое окно не открываем, запрос в очереди, человеку — понятный ответ; память
освободилась — окно открывается само, в Telegram — сообщение."""

import time

import pytest

from gas_pult import tmux, webapp
from gas_pult.config import Config


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.said = []
    monkeypatch.setattr(p.pult, "api", lambda m, **kw: p.said.append((kw.get("chat_id"), kw.get("text"))) or {})
    monkeypatch.setattr(tmux, "make_room", lambda *a: False)
    monkeypatch.setattr(webapp.time, "sleep", lambda s: None)
    return p


def test_enough_memory_starts_now(panel, monkeypatch):
    monkeypatch.setattr(tmux, "free_mb", lambda: tmux.LOW_MB + 500)
    assert panel.mem_gate(lambda: {"id": "@5"}, "shop", 1) == {"id": "@5"}


def test_low_memory_queues_then_starts_and_tells(panel, monkeypatch):
    free = [1400]
    monkeypatch.setattr(tmux, "free_mb", lambda: free[0])
    started = []
    with pytest.raises(ValueError, match=r"мало памяти \(свободно 1\.4 ГБ\).*«shop» в очереди"):
        panel.mem_gate(lambda: started.append(1) or {"id": "@5"}, "shop", 1)
    assert not started and len(panel.start_q) == 1
    free[0] = tmux.LOW_MB + 100                                           # память освободилась
    for _ in range(50):
        if started:
            break
        time.sleep(0.02)
    panel.q_thread.join(2)
    assert started == [1] and not panel.start_q
    assert panel.said and panel.said[-1][0] == 1 and "открыта" in panel.said[-1][1]


def test_queue_gives_up_after_wait(panel, monkeypatch):
    monkeypatch.setattr(tmux, "free_mb", lambda: 500)
    monkeypatch.setattr(panel, "MEM_WAIT", 0)
    with pytest.raises(ValueError):
        panel.mem_gate(lambda: {"id": "@5"}, "shop", 1)
    panel.q_thread.join(2)
    assert not panel.start_q and "не открылась" in panel.said[-1][1]
