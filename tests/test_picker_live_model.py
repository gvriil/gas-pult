"""papasan, вариант A (владелец 20.11, «Да»): окно «Модель и усилие» показывает реальную модель чата из строки
статуса; сохранённая для перезапуска (window_models) расходится — одна строка и выбор «Оставить» / «Запускать»."""
import shutil
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import webapp
from gas_pult.config import Config

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"


def test_keep_model_saves_without_restart():
    p = webapp.Panel(Config(token="1:T", owners=[1], models=["opus", "haiku"]))
    st = {}
    p.pult.state = lambda: st
    p.pult.set_state = lambda **kw: st.update(kw)
    p.tmux.respawn = lambda *a, **k: pytest.fail("перезапуск не нужен")
    assert p.keep_model({"id": "@11"}, "opus") == {"ok": True, "model_own": "opus"}
    assert st["window_models"] == {"@11": "opus"}
    with pytest.raises(ValueError):
        p.keep_model({"id": "@11"}, "gpt")


def page(js_open):
    from playwright.sync_api import sync_playwright
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    out = {}
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome")
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/?demo&dev")
            pg.wait_for_timeout(2500)
            pg.evaluate("openSession('@1'); window.__calls = []; const __api = api;"
                        " window.api = async (u, b) => u === '/api/model'"
                        " ? (__calls.push(b), { ok: true }) : __api(u, b); 0")
            pg.wait_for_timeout(800)
            pg.evaluate(js_open)
            pg.wait_for_selector(".mpick #mpModels [data-m='opus']", timeout=5000)
            out["checked"] = pg.get_attribute("#mpModels [data-m='opus']", "aria-checked")
            out["warn"] = pg.inner_text("#mpWarn") if pg.locator("#mpWarn").count() else ""
            if out["warn"]:
                pg.click("#mpWarn [data-keep=live]")
                pg.wait_for_function("__calls.length === 1", timeout=3000)
                out["call"] = pg.evaluate("__calls[0]")
                out["warn_after"] = pg.locator("#mpWarn").count()
            b.close()
    finally:
        srv.shutdown()
    return out


def need_browser():
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")


def opener(own):
    return ("(() => { const s = { ...cur(), model: 'Opus 5.5', model_own: '" + own + "', profile: 'claude' };"
            " part('picker').then((m) => m.open(s)); })(); 0")


def test_e2e_empty_saved_shows_live_without_warning():
    need_browser()
    o = page(opener(""))
    assert o["checked"] == "true" and o["warn"] == ""


def test_e2e_wrong_saved_shows_live_and_warning_keep_live():
    need_browser()
    o = page(opener("haiku"))
    assert o["checked"] == "true"                                              # работает Opus — подсвечен Opus
    assert "После перезапуска чат запустится на Haiku" in o["warn"] and "Оставить Opus" in o["warn"]
    assert o["call"] == {"w": "@1", "name": "opus", "keep": True} and o["warn_after"] == 0
