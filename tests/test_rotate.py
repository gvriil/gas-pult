"""Поворот телефона сохраняет место в ленте, шторки, панель и поле ввода (владелец 20.11)."""
import shutil
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")


def test_anchor_written_only_at_same_width():
    assert "if (view !== \"session\" || ANCH && ANCH.w !== innerWidth) return;" in INDEX
    assert 'addEventListener("resize", keepAnch);' in INDEX and 'addEventListener("resize", closePop);' not in INDEX
    assert 'tg.onEvent?.("viewportChanged", () => { fitViewport(); keepAnch(); });' in INDEX


def test_e2e_rotate_demo():
    import importlib.util
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    script = Path(__file__).resolve().parent / "e2e" / "rotate_demo.py"
    spec = importlib.util.spec_from_file_location("rotate_demo", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo&dev")
    finally:
        srv.shutdown()


def test_toasts_above_brief():
    """Gemini 20.11, подтверждено в демо: брифинг (z-index 60) закрывал сообщения (#notices, 30)."""
    brief = (WEB / "js/brief.js").read_text(encoding="utf-8")
    assert "body:has(.brief-bg) .notices { z-index: 61; }" in brief
