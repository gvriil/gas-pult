"""GAS-21: неотправленное сообщение не висит вечно — «Отправить ещё раз», «Удалить», повтор при возврате связи."""

from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html"
PAGE = WEB.read_text(encoding="utf-8")


def test_buttons_and_auto_retry_in_page():
    assert 'data-unsend="${esc(p.id)}">Удалить</button>' in PAGE
    resend = 'data-resend="${esc(p.id)}">Отправить ещё раз</button>'
    assert PAGE.count(resend) == 2                          # и «не отправлено», и «нет связи»
    assert 'addEventListener("online", retryLost)' in PAGE
    assert "pending.filter((p) => !p.w || p.w === current)" in PAGE


def test_e2e_unsent_demo():
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
    e2e = Path(__file__).resolve().parent / "e2e" / "unsent_demo.py"
    spec = importlib.util.spec_from_file_location("unsent_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
