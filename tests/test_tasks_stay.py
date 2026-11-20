"""Задачи: после действия человек остаётся на месте (владелец 19.11: «они не должны закрываться, главное — вернуться
туда же, где я был; если курсор куда-то уходит — он должен выделяться»)."""

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"


def test_tasks_return_to_same_place_with_undo():
    js = (WEB / "js/tasks.js").read_text(encoding="utf-8")
    assert "К списку задач" in js and "sh.scrollTop = Y" in js and 'classList.add("just")' in js
    assert '"Отменить"' in js and "5000" in js and 'confirmDanger("Удалить задачу' in js
    assert "tasksSheet(true)" in js                                    # сворачивание группы — без сброса прокрутки


def test_hover_and_focus_visible_in_core():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert ".sheet button:focus-visible, .scn-opt:focus-visible, .toast-undo:focus-visible" in page
    assert "#navList .nrow:focus-visible { outline: none; box-shadow: inset 0 0 0 2px var(--border-focus); }" in page
    assert "outline: 2px solid var(--border-focus)" in page and "min-height: 44px; }" in page
