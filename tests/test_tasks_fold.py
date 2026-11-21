"""Задачи: группы «Срочно», «Сегодня», «Позже», «Сделано» (владелец 21.11, ориентир — Things, Todoist, Linear)
сворачиваются по нажатию на заголовок, состояние запоминается, в заголовке — счётчик; «Сделано» свёрнуто сразу."""

from pathlib import Path

JS = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/js/tasks.js").read_text(encoding="utf-8")


def test_groups_fold_and_urgent_first():
    assert 'const GROUPS = [["urgent", "Срочно"], ["today", "Сегодня"], ["later", "Позже"], ["done", "Сделано"]];' in JS
    body = JS[JS.index("function tasksSheet(keep) {"):JS.index("async function taskQuick")]
    assert 'data-fold="${k}"' in body and "<em>${by[k].length}</em>" in body           # заголовок со счётчиком — кнопка
    assert "if (b.dataset.fold) return fold(b.dataset.fold);" in body
    assert 'const folded = (k, f = folds()) => (k === "done" ? !f[k] : !!f[k]);' in JS   # «Сделано» — свёрнуто
    assert "localStorage.setItem(FOLD_KEY" in JS                                         # состояние запоминается
