"""Копирование в живом терминале (владелец 17.11: «копирование текста и выделение для копирования на айфон»).
Кнопка «Копировать»: выделенное, экран целиком, «Выделить пальцем» — экран текстом (<pre>, iOS: долгое нажатие →
«Скопировать»), ✕ — обратно к эмулятору. Демо, 390 px; xterm.js — с cdnjs (нет сети — пропуск)."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def test_e2e_tty_copy_on_phone():
    sync_api = pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_api.sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&dev&open=@1&noscroll")
            pg.wait_for_selector("#content .msg")
            pg.evaluate("meta.tty = true; window.__cp = [];"
                        " window.copyText = async (t) => { __cp.push(t); return true; }; ttyOpen('@1'); 0")
            try:
                pg.wait_for_selector(".tty .tbox.xt .xterm", timeout=15000)
            except sync_api.TimeoutError:
                pytest.skip("xterm.js с cdnjs не загрузился (нет сети)")
            pg.wait_for_timeout(1500)
            # экран целиком
            pg.click("#ttyCopy")
            pg.locator(".sheet button", has_text="Скопировать экран").click()
            pg.wait_for_function("__cp.length === 1")
            assert "❯" in pg.evaluate("__cp[0]")
            # «Выделить пальцем» — текст, который iOS умеет выделять
            pg.click("#ttyCopy")
            pg.locator(".sheet button", has_text="Выделить пальцем").click()
            pg.wait_for_selector("#ttySelRow:not([hidden])")
            assert not pg.evaluate("document.querySelector('#ttyBox').classList.contains('xt')")
            pg.wait_for_function("document.querySelector('#ttyPre').textContent.includes('❯')", timeout=5000)
            assert pg.evaluate("getComputedStyle(document.querySelector('#ttyPre')).userSelect") == "text"
            pg.evaluate("""() => { const pre = document.querySelector('#ttyPre'), r = document.createRange();
              const node = pre.firstChild; r.setStart(node, 0); r.setEnd(node, 20);
              getSelection().removeAllRanges(); getSelection().addRange(r); }""")
            pg.click("#ttySelAll")
            pg.wait_for_function("__cp.length === 2")
            assert len(pg.evaluate("__cp[1]")) == 20                               # ушло именно выделенное
            # ✕ — снова эмулятор
            pg.click("#ttySelX")
            pg.wait_for_selector(".tty .tbox.xt .xterm")
            assert not errs, errs
            br.close()
    finally:
        srv.shutdown()
