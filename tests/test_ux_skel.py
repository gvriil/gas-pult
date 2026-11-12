"""Скелетоны вместо «Загружаю…» (план UX, пункт 3): разметка и сценарий в браузере (tests/e2e/skel_demo.py).

Пока данных нет — серые заглушки в размер карточки и сообщения; данные встают на их место (CLS < 0,05).
"""

from pathlib import Path

import pytest
from websrc import web_source

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html"
PAGE = web_source()


def test_no_loading_text_where_skeletons_fit():
    assert "<div class=\"empty\">Загружаю…</div>" not in PAGE        # проект, переписка завершённого чата
    assert "<div class=\"empty\">загружаю…</div>" not in PAGE        # открытие сессии
    assert 'morph($("projChats"), skelCards(2))' in PAGE
    assert '$("content").innerHTML = skelMsgs()' in PAGE
    assert 'morph($("sessionsView"), skelCards(3))' in PAGE
    assert "SIM.got === SIM.w ?" in PAGE                 # простой режим: «нет сообщений» — только после ответа


def test_skeleton_motion_is_opacity_only():
    css = PAGE[PAGE.index("/* Скелетоны"):PAGE.index(".msg.skel.ai i")]
    assert "animation: pulse" in css and "@keyframes pulse { 50% { opacity: .35; } }" in PAGE
    assert "prefers-reduced-motion: reduce" in PAGE


def test_e2e_skel_demo():
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
    spec = importlib.util.spec_from_file_location("skel_demo", Path(__file__).resolve().parent / "e2e" / "skel_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
