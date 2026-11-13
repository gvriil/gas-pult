"""Ход, не начавшийся за 5 минут, — сбой, а не «в работе» (#189 п. 4, приём bb «Stuck turns end»).

Было: поставщик принял запрос, Claude Code записал его в журнал («Взял в работу»), а ответа нет — строка статуса
часами показывала «Взял в работу», сессия выглядела занятой. Стало: через ``NO_START`` без слова агента — «Ход не
начался за 5 минут — похоже, сбой у поставщика» и кнопка «Показать экран»; бот перестаёт следить. Если на экране
растёт счётчик токенов (долгое размышление) — это не сбой."""

from pathlib import Path

from test_status_escalation import Clock, follower, rows, run

from gas_pult import activity

INDEX = (Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html").read_text(encoding="utf-8")
T0 = 1_000_000.0


def started(at=T0):
    return {"phase": "started", "text": activity.TEXTS["started"], "since": at, "turn": at}


def test_started_turn_fails_after_no_start():
    assert activity.combine(started(), now=T0 + 200)["phase"] == "started"
    st = activity.combine(started(), screen={"busy": True}, now=T0 + activity.NO_START + 1)
    assert st["phase"] == "failed" and "5 минут" in st["text"] and st["action"] == "screen"
    assert activity.line(st, now=T0 + 400).startswith("⚠️ Ход не начался")


def test_tokens_on_screen_mean_alive():
    st = activity.combine(started(), screen={"busy": True, "tokens": 3400.0}, now=T0 + 900)
    assert st["phase"] == "started"                                     # думает долго, но поставщик отвечает


def test_working_turn_is_never_failed():
    j = {"phase": "working", "text": "Читает файл", "since": T0, "last": T0}
    assert activity.combine(j, screen={"busy": True}, now=T0 + 3600)["phase"] == "working"


def test_tokens_parsed_from_spinner():
    lines = ["● готово", "✻ Pondering… (5m 12s · ↓ 3.4k tokens · esc to interrupt)"]
    assert activity.tokens(lines) == 3400.0
    assert activity.tokens(["✻ Thinking… (12s · esc to interrupt)"]) == 0.0
    assert activity.tokens(["↓ 50 tokens — просто текст в ответе"]) == 0.0      # не строка спиннера


def test_bot_stops_following_failed_turn():
    clock = Clock()
    p = follower([{"phase": "started", "text": "Взял в работу", "since": clock.t},
                  {"phase": "failed", "text": activity.TEXTS["failed"], "since": clock.t, "action": "screen"},
                  {"phase": "done", "text": "", "since": clock.t}], clock)
    run(p, clock)
    edits = [kw for m, kw in p.calls if m == "editMessageText"]
    assert "Ход не начался за 5 минут" in edits[-1]["text"] and "Esc" in edits[-1]["text"]
    assert rows(edits[-1]) == ["scr:@1"]                                # «📺 Экран», без эскалаций
    assert not any("Готово" in kw["text"] for kw in edits)              # дальше не следили


def test_panel_shows_failed_text():
    assert 'failed: "bad"' in INDEX
    assert 'st.phase !== "failed"' in INDEX
