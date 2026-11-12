"""Палитра Ctrl+K / ⌘K (план UX, пункт 5): поиск панели чатов ищет и команды (tests/e2e/palette_demo.py)."""

from pathlib import Path

import pytest
from websrc import web_source

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html"
PAGE = web_source()


def test_palette_is_nav_search_not_second_box():
    assert PAGE.count('type="search" placeholder="Чаты, проекты, команды…"') == 1
    assert "const cmds = q ? palCmds().filter(" in PAGE                 # команды — в той же выдаче renderNav
    assert "if (row.dataset.ncmd)" in PAGE
    body = PAGE[PAGE.index("function palCmds()"):PAGE.index("function navOpen(on)")]
    assert 'go("go:settings")' in body and "newChat()" in body
    for x in ("delete", "Удалить", "Завершить"):                          # в палитре — только безопасные переходы
        assert x not in body, x


def test_e2e_palette_demo():
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
    e2e = Path(__file__).resolve().parent / "e2e" / "palette_demo.py"
    spec = importlib.util.spec_from_file_location("palette_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
