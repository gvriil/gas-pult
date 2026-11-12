"""Меньше шума (план UX, пункт 9): разметка и сценарий в браузере (tests/e2e/quiet_demo.py).

Без «обновлено ЧЧ:ММ:СС» (о связи — только «нет связи»), без дубля «Пульт / хост» на компьютере, «⋯» — глаголами,
«Удалить» — плашкой «Отменить» вместо окна «Вы уверены?».
"""

from pathlib import Path

import pytest
from websrc import web_source

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html"
PAGE = web_source()


def test_no_updated_clock():
    assert "· обновлено ${" not in PAGE and "обновлено </span>" not in PAGE
    assert "#live:not(.stale) { display: none; }" in PAGE


def test_no_duplicate_title_and_verbs():
    assert "body.no-dup.has-nav:not(.side-mini) #top .titles { visibility: hidden; }" in PAGE
    for noun in ('label: "Новая папка", icon: "plus", run: () => newFolder() }', 'label: "Главная: сессии и проекты"',
                 'label: "Все действия…"', 'label: "Фокус-ссылка"'):
        assert noun not in PAGE, noun


def test_delete_with_undo_not_confirm():
    body = PAGE[PAGE.index("function chatDelete(body, name) {"):PAGE.index("async function chatRestore")]
    assert "undoBar(" in body and "confirmDanger(" not in body
    assert "function navDelete(s) { chatDelete(" in PAGE


def test_e2e_quiet_demo():
    import importlib.util
    import shutil
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB.parent)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    e2e = Path(__file__).resolve().parent / "e2e" / "quiet_demo.py"
    spec = importlib.util.spec_from_file_location("quiet_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
