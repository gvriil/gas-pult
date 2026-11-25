"""Перетаскивание и вставка файлов в панель (владелец 17.11, Мак): картинка, брошенная на поле ввода или ленту, и
скриншот из буфера загружаются как через скрепку (upload ядра); только путь к файлу — подсказка, текст в поле не идёт.
Демо панели в Chromium (Playwright): загрузка в демо — window.__demoUploads (js/upload.js)."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"

DROP = """([sel, withFile, text]) => {
  const dt = new DataTransfer();
  if (withFile) {
    const c = document.createElement('canvas'); c.width = 40; c.height = 30;
    const b = atob(c.toDataURL('image/png').split(',')[1]);
    dt.items.add(new File([Uint8Array.from(b, (x) => x.charCodeAt(0))], 'IMAGE 2026-11-17.png', {type: 'image/png'}));
  }
  if (text) dt.setData('text/plain', text);
  const el = document.querySelector(sel);
  for (const k of ['dragenter', 'dragover', 'drop'])
    el.dispatchEvent(new DragEvent(k, {dataTransfer: dt, bubbles: true, cancelable: true}));
  return document.querySelector('#input').value;
}"""

PASTE = """() => {
  const dt = new DataTransfer();
  dt.items.add(new File([new Uint8Array([137, 80, 78, 71])], 'image.png', {type: 'image/png'}));
  const ev = new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true});
  document.querySelector('#input').dispatchEvent(ev);
  return ev.defaultPrevented;
}"""


def test_core_loads_part_and_part_uses_upload():
    core = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "js" / "dropfiles.js").read_text(encoding="utf-8")
    assert 'part("dropfiles")' in core and "async function upload(" in core
    assert "upload(named(f)" in js and "getAsFile()" in js and 'addEventListener("paste"' in js


def test_e2e_drop_and_paste():
    sync_api = pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_api.sync_playwright() as p:
            br = p.chromium.launch()
            pg = br.new_page(viewport={"width": 1366, "height": 860})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&dev&open=@1&noscroll")
            pg.wait_for_selector("#content .msg")
            pg.wait_for_function("!!window.dropFilesOf", timeout=8000)
            # картинка на поле ввода — загрузка, текст пути в поле не вставлен
            assert pg.evaluate(DROP, ["#input", True, "/var/folders/37/T/IMAGE 2026-11-17.png"]) == ""
            pg.wait_for_function("(window.__demoUploads || []).length === 1", timeout=10000)
            # на ленту — тоже
            pg.evaluate(DROP, ["#content", True, ""])
            pg.wait_for_function("(window.__demoUploads || []).length === 2", timeout=10000)
            # только путь, без файла — подсказка, загрузки нет, в поле пусто
            assert pg.evaluate(DROP, ["#input", False, "file:///var/folders/37/T/IMAGE.jpg"]) == ""
            pg.wait_for_function("document.body.innerText.includes('только путь к файлу')", timeout=3000)
            # скриншот из буфера — загрузка с именем «снимок-…»
            assert pg.evaluate(PASTE) is True
            pg.wait_for_function("(window.__demoUploads || []).length === 3", timeout=10000)
            assert pg.evaluate("document.querySelector('#attach').innerText").count("снимок-") == 1
            # подсветка снята после броска
            assert not pg.evaluate("document.body.classList.contains('drop-on')")
            assert not errs, errs
            br.close()
    finally:
        srv.shutdown()
