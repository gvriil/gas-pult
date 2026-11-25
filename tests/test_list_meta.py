"""Список чатов: строка метаданных под названием и точка «новый ответ» (#189, UI/UX п.7–8)."""

import importlib.util
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "gas_pult" / "web"


def test_nav_row_has_meta_and_unread_dot():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "const navMeta = (s) =>" in html and '<span class="nnew"></span>' in html
    assert '(mt ? " · " + mt : "")' in html and '<span class="nmeta">' not in html    # 20.11: модель — в подсказке
    assert ".nrow .nnew {" in html and "background: var(--accent-primary)" in html


def test_e2e_list_meta_demo():
    pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    spec = importlib.util.spec_from_file_location("list_meta_demo", ROOT / "tests" / "e2e" / "list_meta_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&dev")
    finally:
        srv.shutdown()
