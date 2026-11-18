"""Плавный чат (GAS-29): растущий ответ — один узел, лента идёт за ним без перескоков, разметка — до первой отрисовки.

Замер в браузере — tests/e2e/chat_smooth.py (демо, 390 и 1366). Числа на 18.11 (до → после), телефон 390:
скачок прокрутки за кадр 141 → 16 px, скачок высоты ответа за кадр 141 → 19 px, пузырь пересоздавался 6 раз → 1 узел,
длинный кусок (3 экрана) — мгновенно в конец → начало куска на экране и «новое ↓»; открытие при медленной сети к CDN:
ответ менял высоту на глазах на 563 px → 0 раз.
"""

from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
PAGE = (WEB / "index.html").read_text(encoding="utf-8")


def body(start, end):
    return PAGE[PAGE.index(start):PAGE.index(end, PAGE.index(start))]


def test_growing_answer_keeps_node():
    rc = body("function renderChat(toBottom) {", "\n}\n")
    assert "gm.replaceChildren(...n.childNodes); gm.__s = src; grown.push(gm);" in rc
    assert "msgs.push(...grown);" in rc


def test_follow_not_jump():
    mc = body("function mergeChat(h) {", "\n}\n")
    assert "renderChat(atBottom)" not in mc and "return follow(h0);" in mc
    fo = body("function follow(h0) {", "\n}\n")
    assert "56)" in fo and "SC.clientHeight * .7" in fo and 'classList.add("new")' in fo
    assert "#content.chat { overflow-anchor: none; }" in PAGE
    assert "if (Date.now() < glideT) return;" in PAGE         # stickRO не дёргает к низу на ходу follow
    assert "stick = glideT = 0;" in PAGE                      # палец, колесо, клавиши — человек ведёт сам


def test_markdown_before_first_paint():
    lc = body("async function loadContent() {", "\n}\n")
    assert 'tab === "chat" && !mdReady() && Promise.race([mdLoad(),' in lc


def test_no_name_clash():
    assert PAGE.count("function unroll(") == 1 and PAGE.count("function follow(") == 1
    assert PAGE.count("function grow(") == 1                   # grow — поле ввода, не трогаем


def test_e2e_chat_smooth():
    import importlib.util
    import shutil
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    e2e = Path(__file__).resolve().parent / "e2e" / "chat_smooth.py"
    spec = importlib.util.spec_from_file_location("chat_smooth", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
