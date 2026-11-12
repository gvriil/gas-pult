"""Лента ~760 px по центру и появление новых сообщений (план UX, пункт 6): разметка и tests/e2e/feed_demo.py."""

from pathlib import Path

import pytest
from websrc import web_source

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html"
PAGE = web_source()


def test_feed_column_and_enter_animation():
    assert "body.split #session, body.split .dock > *, body.split .tabsbar .seg { max-width: 760px; }" in PAGE
    assert "@keyframes msgin { from { opacity: 0; transform: translateY(8px); }" in PAGE
    assert ".chat .msg.enter { animation: msgin .15s ease-out; }" in PAGE
    assert ".chat .msg { margin: 0 0 14px; }" in PAGE                 # без анимации у каждого сообщения
    assert PAGE.count('el.classList.add("enter")') == 2               # полный и простой режим


def test_e2e_feed_demo():
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
    spec = importlib.util.spec_from_file_location("feed_demo", Path(__file__).resolve().parent / "e2e" / "feed_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
