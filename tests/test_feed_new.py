"""Разделитель «Новое» в ленте перед первым ответом агента после прошлого просмотра (#189, UI/UX п.5)."""

import importlib.util
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "gas_pult" / "web"


def test_divider_code():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "const NEWI = {" in html and 'class="newdiv"' in html and "NEWI.k = \"\"" in html
    assert ".newdiv {" in html and "color: var(--accent-primary)" in html


def test_e2e_feed_new_demo():
    pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    spec = importlib.util.spec_from_file_location("feed_new_demo", ROOT / "tests" / "e2e" / "feed_new_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&dev")
    finally:
        srv.shutdown()
