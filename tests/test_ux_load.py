"""Загрузка без лишнего (план UX, пункт 10): разметка панели и сценарий в браузере (tests/e2e/load_demo.py).

marked и DOMPurify не в <head> — грузятся после первого показа (mdLoad), ответы рисует md(); словарь берётся из
localStorage сразу, свежий — в фоне.
"""

from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html"
PAGE = WEB.read_text(encoding="utf-8")


def test_markdown_libs_after_first_paint():
    head = PAGE[:PAGE.index("<style>")]
    assert "marked" not in head and "purify" not in head
    assert "marked.parse(" not in PAGE.replace("DOMPurify.sanitize(marked.parse(t || \"\"))", "")
    assert PAGE.count("afterPaint(mdLoad)") >= 3                    # полный режим, фокус, простой режим


def test_dict_from_cache_first():
    assert 'localStorage.getItem("dict:" + LANG)' in PAGE
    assert 'store("dict:" + lang, t)' in PAGE


def test_e2e_load_demo():
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
    spec = importlib.util.spec_from_file_location("load_demo", Path(__file__).resolve().parent / "e2e" / "load_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
