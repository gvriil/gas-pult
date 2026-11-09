"""Панель чатов слева (как в ChatGPT / Claude.ai): разметка и сценарий в браузере (tests/e2e/nav_demo.py).

Статически: ✎ «Новый чат» сверху панели, поиск (Ctrl+K), «⋯» у строки открывает меню у строки (popMenu, не sheet),
первым — «Закрепить»; удаление — с плашкой «Отменить» до запроса к серверу; окно нового чата — при первой отправке.
"""

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html"
PAGE = WEB.read_text(encoding="utf-8")


def fn(name: str) -> str:
    i = PAGE.index(f"function {name}(")
    return PAGE[i:PAGE.index("\n}\n", i)]


def test_nav_markup():
    head = PAGE[PAGE.index('<aside class="nav" id="nav"'):PAGE.index("</aside>")]
    assert head.index('id="navNew"') < head.index('id="navList"'), "«Новый чат» — сверху"
    for x in ('id="navSearchBtn"', 'id="navMoreBtn"', 'id="navQ"'):
        assert x in head, x
    for x in ('id="navBtn"', 'id="composeBtn"'):
        assert x in PAGE, x


def test_row_menu_is_popover_and_pin_first():
    items = fn("navItems")
    sess = items[items.index("const s = sessions"):]
    assert sess.index('"Открепить" : "Закрепить"') < sess.index('"Переименовать"') < sess.index('"Удалить"')
    assert "sheet(" not in fn("popMenu")
    assert re.search(r'e\.target\.closest\("\[data-nmore\]"\)\) return popMenu', PAGE)


def test_delete_waits_for_undo_and_new_chat_waits_for_send():
    d = fn("chatDelete")                                                 # navDelete — через chatDelete (пункт 9)
    assert "chatDelete(" in fn("navDelete")
    assert "undoBar(" in d and "/api/chat/delete" in d
    assert d.index("undoBar(") < d.index("/api/chat/delete"), "запрос — только после «Отменить» не нажали"
    assert "/api/project/session" not in fn("newChat") and "/api/new" not in fn("newChat")
    assert "/api/project/session" in fn("draftSend")
    assert "if (DRAFT) return draftSend();" in fn("sendText")


def test_recent_by_last_message():
    assert "const lastMsg = (s) => Math.max(+s.said || 0, +s.asked || 0)" in PAGE


def test_e2e_nav_demo():
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
    spec = importlib.util.spec_from_file_location("nav_demo", Path(__file__).resolve().parent / "e2e" / "nav_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
