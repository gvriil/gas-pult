"""Поле ввода без лишней раскладки (план UX, пункт 8): разметка и сценарий в браузере (tests/e2e/input_demo.py).

Поле меряется раз в кадр (fitLines в requestAnimationFrame), кнопка «к последнему» сдвигается transform.
"""

from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html"
PAGE = WEB.read_text(encoding="utf-8")


def test_fit_once_per_frame_and_transform_button():
    fit = PAGE[PAGE.index("function fitLines"):PAGE.index("\n}\n", PAGE.index("function fitLines"))]
    assert "if (t.__fit) return;" in fit and "requestAnimationFrame" in fit
    assert '$("toBottom").style.bottom' not in PAGE
    assert "translateY(calc(-1 * var(--tb, 0px)))" in PAGE and ".tobottom { transition: transform" in PAGE


def test_e2e_input_demo():
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
    e2e = Path(__file__).resolve().parent / "e2e" / "input_demo.py"
    spec = importlib.util.spec_from_file_location("input_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
