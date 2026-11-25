"""iPad 17.11 (скриншот владельца): Telegram показывает мини-приложение плавающим окном ~420 px на экране 1280 px,
expand() раскрывает только по высоте. Окно намного уже экрана — панель просит полный экран (Bot API 8.0
requestFullscreen); на телефоне (окно = экран) — нет; выключено в настройках — нет."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"

# Поддельный Telegram.WebApp: любые незнакомые методы — пустые; requestFullscreen — счётчик
STUB = """(() => { window.__fs = 0; const base = { initData: '', initDataUnsafe: {}, colorScheme: 'light',
  themeParams: {}, platform: 'ios', version: '8.0', isFullscreen: false, contentSafeAreaInset: { top: 46 },
  safeAreaInset: { top: 24 }, isVersionAtLeast: () => true, requestFullscreen() { window.__fs++; },
  exitFullscreen() {}, onEvent() {}, offEvent() {} };
  const noop = new Proxy(function () {}, { get: () => noop, apply: () => undefined });
  window.Telegram = { WebApp: new Proxy(base, { get: (t, k) => (k in t ? t[k] : noop) }) }; })();"""


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.mark.parametrize("view,screen,off,want", [
    (420, 1280, False, 1),      # iPad: плавающее окно — полный экран
    (390, 390, False, 0),       # iPhone: окно во весь экран — не трогаем
    (420, 1280, True, 0),       # выключено в настройках
])
def test_fullscreen_only_for_floating_window(view, screen, off, want):
    sync_api = pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_api.sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={"width": view, "height": 800}, screen={"width": screen, "height": 900})
            pg.add_init_script(STUB + ("localStorage.setItem('tgFull', '0');" if off else ""))
            pg.route("**/telegram-web-app.js", lambda r: r.fulfill(body="", content_type="text/javascript"))
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&dev")
            pg.wait_for_timeout(1500)
            assert pg.evaluate("window.__fs") == want
            br.close()
    finally:
        srv.shutdown()
