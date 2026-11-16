"""Правка своего сообщения (#258): «Изменить» у своего сообщения → текст в поле, полоска «Исправляете сообщение»;
отправка — с пометкой исправления; без правок — как есть; «Отмена» — поле пустое. Демо панели в Chromium."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def test_e2e_edit_message():
    sync_api = pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_api.sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={"width": 390, "height": 844})
            errs, sent = [], []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&open=@1&noscroll")
            pg.wait_for_selector("#content .msg.me [data-medit]")
            orig = pg.evaluate("msgText(document.querySelector('#content .msg.me'))")
            pg.evaluate("window.__api = window.api; window.api = (...a) => { if (a[0] === '/api/send') "
                        "window.__sent = [...(window.__sent || []), a[1].text]; return window.__api(...a); }; 0")
            # «Отмена» — поле пустое, полоски нет
            pg.click("#content .msg.me [data-medit]")
            pg.wait_for_selector("#editBar")
            assert pg.input_value("#input") == orig
            pg.click("#editBar [data-editx]")
            assert pg.locator("#editBar").count() == 0 and pg.input_value("#input") == ""
            # правка — с пометкой исправления
            pg.click("#content .msg.me [data-medit]")
            pg.fill("#input", "Покажи, что изменилось за вчера")
            pg.evaluate("sendText()")
            pg.wait_for_function("(window.__sent || []).length === 1")
            text = pg.evaluate("window.__sent[0]")
            assert text.startswith("Исправление моего предыдущего сообщения") and text.endswith("за вчера")
            assert pg.locator("#editBar").count() == 0
            sent = pg.evaluate("window.__sent")
            assert not errs, errs
            assert len(sent) == 1
            br.close()
    finally:
        srv.shutdown()
