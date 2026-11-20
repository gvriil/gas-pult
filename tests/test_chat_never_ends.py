"""Владелец 20.11: чат не заканчивается. Спит, остановлен или завершён — для человека обычный чат с тихой точкой «спит»;
первое сообщение будит его само, без «Перезапустить» и «Продолжить»; не проснулся — причина и «Попробовать ещё»."""
from pathlib import Path

INDEX = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")


def test_one_quiet_sleep_state():
    assert 'stopped: { label: "спит", cls: "s-idle s-sleep" }' in INDEX
    assert 'sleep: { label: "спит", cls: "s-idle s-sleep" }' in INDEX
    assert "💤" not in INDEX and "остановлена" not in INDEX.split("const ST = ")[1].split("\n")[1]


def test_no_restart_or_continue_buttons():
    assert "Перезапустить — продолжить разговор" not in INDEX
    assert "data-revive" not in INDEX
    assert "сначала «Перезапустить»" not in INDEX
    assert "Продолжить этот чат" not in INDEX
    assert 'placeholder="Напишите — чат продолжится"' in INDEX


def test_message_wakes_the_chat():
    body = INDEX[INDEX.index("async function deliver(p, restore) {"):]
    assert body.index("if (!await wake(p.w))") < body.index('await api("/api/send"')
    assert 'waking: "чат просыпается' in INDEX
    assert 'Попробовать ещё</button>' in INDEX and "data-rewake" in INDEX
    assert "if (WAKING.has(id)) return WAKING.get(id);" in INDEX        # одно пробуждение на окно
