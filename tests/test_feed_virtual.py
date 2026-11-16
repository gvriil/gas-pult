"""Виртуализация ленты (#258): в DOM — последние 120 сообщений; «Показать ранее» сначала раскрывает уже
загруженные (без запроса), место чтения не прыгает; новое сообщение — внизу; markdown не пересчитывается."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"

FILL = """(n) => {
  hist = Array.from({length: n}, (_, k) => ({ i: k + 1, role: k % 2 ? "assistant" : "user", ts: "2026-11-17 10:00",
    text: k % 2 ? "Ответ **" + k + "**\\n\\n- пункт" : "Вопрос " + k }));
  histMore = false; renderChat(true);
}"""


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def test_e2e_feed_virtual():
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
            pg.wait_for_timeout(1500)                                         # опросы демо успокоились
            pg.evaluate("window.__h = 0; window.__api = window.api; window.api = (...a) => { if (String(a[0])"
                        ".startsWith('/api/history')) window.__h++; return window.__api(...a); }; 0")
            pg.evaluate(FILL, 600)
            assert pg.evaluate("document.querySelectorAll('#content .msg').length") == 120
            assert pg.evaluate("document.querySelector('#content .msg[data-i]').dataset.i") == "481"
            assert pg.locator("#older").count() == 1
            # «Показать ранее» — без запроса, место чтения на месте
            pg.evaluate("SC.scrollTop = 0")
            top = pg.evaluate("document.querySelector('#content .msg[data-i=\"481\"]').getBoundingClientRect().top")
            pg.click("#older")
            assert pg.evaluate("document.querySelectorAll('#content .msg').length") == 240
            after = pg.evaluate("document.querySelector('#content .msg[data-i=\"481\"]').getBoundingClientRect().top")
            assert abs(after - top) < 40, (top, after)
            assert pg.evaluate("window.__h") == 0                                 # с сервера ничего не грузили
            # новое сообщение — в ленте, markdown ответа — из кэша (тот же текст — тот же HTML)
            pg.evaluate("hist = [...hist, {i: 601, role: 'assistant', ts: '2026-11-17 10:01', text: 'новое'}]; "
                        "renderChat(true)")
            assert pg.evaluate("document.querySelector('#content .msg[data-i=\"601\"]') !== null")
            assert pg.evaluate("MDC.size") >= 120
            assert not errs, errs
            br.close()
    finally:
        srv.shutdown()
