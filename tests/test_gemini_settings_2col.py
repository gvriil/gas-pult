"""Gemini 21.11, топ-15 №6 (приём 2): «Настройки» на ПК — одно окно 720×560, слева разделы, справа пункты,
без «‹ Назад», × справа вверху. Строится из обычной шторки раздела; «‹ Назад» во вложенных окнах
возвращает в это окно."""
import shutil
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"


def test_code():
    js = (WEB / "js/settings.js").read_text(encoding="utf-8")
    assert "const wide = () => split() && innerWidth >= 900;" in js
    assert "if (wide()) return openWide(gs[at] ? at : 0, gs);" in js
    assert "if (sheetFrom) sheetFrom.open = () => open(at);" in js
    assert "width: min(720px" in js and "height: min(560px" in js


def test_e2e_wide_window():
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    from playwright.sync_api import sync_playwright
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome")
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
            pg.wait_for_timeout(2500)
            pg.click("#settingsBtn")
            pg.wait_for_selector(".sheet.setwide .setnav button.on", timeout=5000)
            box = pg.locator(".sheet.setwide").bounding_box()
            assert box["width"] <= 721 and box["height"] <= 561
            assert pg.locator(".setnav button[data-sec]").count() >= 4
            pg.click(".setnav button[data-sec='1']")
            pg.wait_for_selector(".setnav button[data-sec='1'].on", timeout=3000)
            assert pg.locator(".sheet-bg").count() == 1
            pg.locator(".setpane button[data-i]", has_text="Уведомления").first.click()
            pg.wait_for_selector(".sheet .sback", timeout=4000)
            pg.locator(".sheet .sback").last.click()
            pg.wait_for_selector(".sheet.setwide .setnav button[data-sec='1'].on", timeout=3000)
            pg.click(".setwide .setx")
            pg.wait_for_timeout(300)
            assert pg.locator(".sheet-bg").count() == 0 and not errs
            b.close()
    finally:
        srv.shutdown()
