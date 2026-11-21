"""Gemini 21.11, топ-15 №15 (приём 1, как в Linear): на ПК ⌘K / Ctrl+K — палитра по центру: чаты, проекты, действия;
↑↓, Enter, Esc. Действия — тот же список, что у поиска в панели (palCmds). На телефоне — поиск в панели, как было."""
import shutil
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"


def test_code():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'const palOpen = () => split() ? part("palette").then((m) => m.open()) : navSearch(true);' in page
    js = (WEB / "js/palette.js").read_text(encoding="utf-8")
    assert "const acts = palCmds().map(" in js


def test_e2e_palette():
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    from playwright.sync_api import sync_playwright
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/?demo"
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome")
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base)
            pg.wait_for_timeout(2500)
            pg.keyboard.press("Control+k")
            pg.wait_for_selector(".pal input", timeout=3000)
            assert pg.evaluate("document.activeElement.closest('.pal') !== null")
            assert pg.locator(".pal .grp").first.inner_text().lower() == "действия"   # пусто — сначала действия
            pg.keyboard.type("тест")
            pg.wait_for_timeout(200)
            pg.keyboard.press("Enter")
            pg.wait_for_function("current === '@1'", timeout=3000)
            assert pg.locator(".pal").count() == 0
            pg.keyboard.press("Control+k")
            pg.wait_for_selector(".pal", timeout=3000)
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(200)
            assert pg.locator(".pal").count() == 0 and not errs
            m = b.new_page(viewport={"width": 390, "height": 844})
            m.goto(base)
            m.wait_for_timeout(2400)
            m.evaluate("navSearch(true)")
            m.wait_for_timeout(400)
            assert m.locator(".pal").count() == 0 and m.is_visible("#navQ")
            b.close()
    finally:
        srv.shutdown()
