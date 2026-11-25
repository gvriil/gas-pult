"""После клавиатуры на iPhone не остаётся белой полосы (владелец 16.11)."""

from pathlib import Path

import pytest


def test_e2e_keyboard_gap():
    import importlib.util
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    pytest.importorskip("playwright.sync_api")
    web = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(web)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    e2e = Path(__file__).parent / "e2e" / "keyboard_gap_demo.py"
    spec = importlib.util.spec_from_file_location("keyboard_gap_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&dev")
    finally:
        srv.shutdown()
