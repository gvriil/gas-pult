"""GAS-34: длинная запись — фоново, запись не теряется (сценарий в браузере — tests/e2e/voicejob_demo.py)."""

from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"


def test_page_uses_job_and_keeps_record():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'm.sttJob(blob, ctl.signal)' in page and 'download="запись.webm"' in page
    js = (WEB / "js" / "voicejob.js").read_text(encoding="utf-8")
    assert '"/api/stt?job=1"' in js and "indexedDB.open" in js


def test_e2e_voicejob_demo():
    import importlib.util
    import shutil
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    e2e = Path(__file__).resolve().parent / "e2e" / "voicejob_demo.py"
    spec = importlib.util.spec_from_file_location("voicejob_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
