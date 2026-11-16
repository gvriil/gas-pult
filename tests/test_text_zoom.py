"""Масштаб текста панели жестом и A+/A− (владелец 16.11; WCAG 1.4.4 — до 200 %)."""

from pathlib import Path

import pytest


def test_e2e_text_zoom():
    import importlib.util
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    pytest.importorskip("playwright.sync_api")
    web = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(web)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    spec = importlib.util.spec_from_file_location("zoom_demo", Path(__file__).parent / "e2e" / "zoom_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo")
    finally:
        srv.shutdown()
