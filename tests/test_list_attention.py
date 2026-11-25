"""Внимание к сессиям (#189, UI/UX): счётчик на вкладке и значке приложения."""

import importlib.util
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "gas_pult" / "web"


def _e2e(name: str):
    pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / "e2e" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&dev")
    finally:
        srv.shutdown()


def test_badge_code():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "function attnBadge()" in html and "navigator.setAppBadge?.(n)" in html
    assert "attnBadge();" in html


def test_e2e_badge_demo():
    _e2e("badge_demo")
