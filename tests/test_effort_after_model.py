"""Владелец 17.11: «после того как выбрал модель — обязательно дать выбрать усилия». Выбор модели → сразу шторка
«Усилие для …» с отметкой текущего; у поставщика без усилий (не Claude) — шага нет. Демо панели в Chromium."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def test_e2e_effort_step_after_model():
    sync_api = pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_api.sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={"width": 390, "height": 844})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&open=@1&noscroll")
            pg.wait_for_selector("#content .msg")
            pg.evaluate("window.__api = api; window.api = async (path, body) => path === '/api/model'"
                        " ? { id: body.w } : __api(path, body); cur().effort = 'high'; cur().profile = 'claude'; 0")
            pg.evaluate("setModel(cur(), 'sonnet', 'sonnet')")
            pg.wait_for_function("[...document.querySelectorAll('.sheet h3, .sheet .title, .sheet')]"
                                 ".some((e) => e.textContent.includes('Усилие для «sonnet»'))", timeout=5000)
            on = pg.evaluate("[...document.querySelectorAll('.sheet button.on')].map((b) => b.textContent)")
            assert any("Высокий" in t for t in on), on                          # текущее отмечено
            pg.evaluate("document.querySelectorAll('.sheet-bg').forEach((b) => b.remove())")
            # другой поставщик — шага нет
            pg.evaluate("cur().profile = 'deepseek'; setModel(cur(), 'opus', 'opus')")
            pg.wait_for_timeout(800)
            assert not pg.evaluate("[...document.querySelectorAll('.sheet')]"
                                   ".some((e) => e.textContent.includes('Усилие'))")
            assert not errs, errs
            br.close()
    finally:
        srv.shutdown()
