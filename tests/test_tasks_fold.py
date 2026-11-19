"""Задачи сверху (владелец 19.11: «таски удобно сворачивать по группировкам срочно-важно»): группы сворачиваются по
нажатию на заголовок, состояние запоминается, в заголовке — счётчик; «Ждут вас» — первой группой."""

from pathlib import Path

JS = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/js/tasks.js").read_text(encoding="utf-8")


def test_groups_fold_and_waiting_first():
    body = JS[JS.index("function tasksSheet(keep) {"):JS.index('helpSheet("sheet.tasks")')]
    assert body.index('group("w", "Ждут вас", waiting)') < body.index("for (const q of [1, 0, 2, 3, 4])")
    assert 't.status !== "waiting"' in body                                     # в квадрантах — без «ждут вас»
    assert "`${title} · ${list.length}`" in body and "run: () => fold(k)" in body # заголовок со счётчиком — кнопка
    assert 'const FOLD_KEY = "tq:fold"' in JS and "localStorage.setItem(FOLD_KEY" in JS   # состояние запоминается
