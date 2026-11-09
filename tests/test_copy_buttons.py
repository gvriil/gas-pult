"""«Копировать» у каждого сообщения и блока кода: разметка и сценарий в браузере (tests/e2e/copy_demo.py)."""

import json
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html"
PAGE = WEB.read_text(encoding="utf-8")


def test_every_message_gets_copy_button():
    feed = PAGE[PAGE.index("function renderChat("):PAGE.index("voiceUi();", PAGE.index("function renderChat("))]
    assert feed.count("mCopyBtn()") == 2                   # ваше сообщение и неотправленное
    assert 'data-mcopy="1">${ic("copy", "s16")}${esc(copyLbl())}' in feed      # ответ — с подписью, после времени
    assert feed.index('class="when" style="margin-left:auto"') < feed.index('data-mcopy="1">')
    smsg = PAGE[PAGE.index("function sMsg("):PAGE.index("function sRender(")]
    assert smsg.count("mCopyBtn()") == 2                   # простой режим: и ваше, и ответ
    assert "msgs.forEach(codeCopy)" in PAGE and "fresh.forEach(codeCopy)" in PAGE and "codeCopy(list)" in PAGE


def test_copy_has_webview_fallback_and_flash():
    body = PAGE[PAGE.index("async function copyText("):PAGE.index("function codeCopy(")]
    assert 'document.execCommand("copy")' in body and "return false;" in body
    flash = PAGE[PAGE.index("function copiedFlash("):PAGE.index("function msgText(")]
    assert "1500" in flash


def test_i18n_keys():
    for lang in ("ru", "en"):
        d = json.loads((WEB.parent / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        assert {"copy.done", "copy.code", "copy.msg"} <= d.keys()


def test_e2e_copy_demo():
    import importlib.util
    import shutil
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB.parent)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    spec = importlib.util.spec_from_file_location("copy_demo", Path(__file__).resolve().parent / "e2e" / "copy_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
