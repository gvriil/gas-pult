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
            pg.evaluate("window.__api = api; window.__calls = [];"
                        " window.api = async (path, body) => path === '/api/model'"
                        " ? (__calls.push(body), { id: body.w }) : __api(path, body); cur().effort = 'high';"
                        " cur().profile = 'claude'; 0")
            # 19.11: модель и усилие — одно окно (js/picker.js): слева модели, справа усилия выбранной модели
            pg.evaluate("ACTIONS.models()")
            pg.wait_for_selector(".mpick #mpModels [data-m='sonnet']", timeout=5000)
            pg.locator("#mpModels [data-m='haiku']").click()
            assert pg.locator("#mpEff .mp-none").count() == 1                   # у Haiku усилий нет
            pg.locator("#mpModels [data-m='sonnet']").click()
            assert pg.evaluate("__calls.length") == 0                 # смена модели — по выбору усилия
            pg.locator("#mpEff [data-e='max']").click()
            pg.wait_for_function("__calls.length === 1", timeout=5000)
            assert pg.evaluate("__calls[0]") == {"w": "@1", "name": "sonnet", "effort": "max"}
            assert pg.locator(".mpick").count() == 0 and pg.evaluate("tab") == "chat"   # «Экран» не открывается
            # другой поставщик (свой ключ) — усилий нет, модель — кнопкой
            pg.evaluate("cur().profile = 'deepseek'; ACTIONS.models()")
            pg.wait_for_selector(".mpick #mpEff .mp-none", timeout=5000)
            pg.locator("#mpEff [data-e]").click()
            pg.wait_for_function("__calls.length === 2", timeout=5000)
            assert "effort" not in pg.evaluate("__calls[1]")
            assert not errs, errs
            br.close()
    finally:
        srv.shutdown()
