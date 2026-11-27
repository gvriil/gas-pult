"""Лента держит низ при ресайзе, если вы были внизу (#189, UI/UX п.4)."""

import importlib.util
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "gas_pult" / "web"


def test_stick_code():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "let atBot = false;" in html and "atBot = atEnd(24);" in html
    assert 'view === "session" && atBot) SC.scrollTop = SC.scrollHeight' in html and "stickRO.observe(SC);" in html


def test_e2e_feed_bottom_demo():
    pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    spec = importlib.util.spec_from_file_location("feed_bottom_demo", ROOT / "tests" / "e2e" / "feed_bottom_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&dev")
    finally:
        srv.shutdown()
