"""papasan, владелец 20.11: окно «Модель и усилие» подсвечивает модель чата (s.model из строки статуса), если её не
выбирали вручную; у Haiku есть усилия (claude -p --model haiku --effort low отвечает без ошибки)."""
import shutil
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"


def test_code():
    js = (WEB / "js/picker.js").read_text(encoding="utf-8")
    assert "let sel = (s ? live || saved : DRAFT?.model)" in js   # реальная модель первой (вариант A, 20.11)
    assert 'const hasEffort = (profile) => (profile || "claude") === "claude";' in js


def test_e2e_picker_highlights_chat_model():
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
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
            pg.wait_for_timeout(2500)
            pg.evaluate("openSession('@1'); 0")
            pg.wait_for_timeout(1000)
            pg.evaluate("(() => { const s = { ...cur(), model: 'Haiku 5.5', model_own: '', profile: 'claude' };"
                        " part('picker').then((m) => m.open(s)); })(); 0")
            pg.wait_for_selector(".mpick #mpModels [data-m='haiku']", timeout=5000)
            on = pg.get_attribute("#mpModels [data-m='haiku']", "aria-checked")
            assert on == "true"                                                  # модель чата, а не умолчание
            assert pg.locator("#mpEff [data-e='low']").count() == 1                         # у Haiku — усилия
            b.close()
    finally:
        srv.shutdown()
