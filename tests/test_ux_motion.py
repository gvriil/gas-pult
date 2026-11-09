"""Переходы экранов на телефоне (план UX, пункт 7): разметка и сценарий касаниями (tests/e2e/motion_demo.py).

Сессия въезжает справа (200 мс, transform); свайп от левого края в сессии — «назад» с живым следованием за пальцем;
панель чатов от края — только на главной (в сессии — по ☰), чтобы жесты не спорили.
"""

from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html"
PAGE = WEB.read_text(encoding="utf-8")


def test_transitions_transform_only():
    assert "@keyframes slidein { from { transform: translateX(100%); } to { transform: none; } }" in PAGE
    assert "#session.slide-in, .dock.slide-in { animation: slidein .2s" in PAGE
    assert "body.back-anim #session, body.back-anim .dock { transition: transform .2s" in PAGE
    assert "el.style.transform = `translateX(${d.dx}px)`" in PAGE


def test_edge_swipe_split_between_nav_and_back():
    assert 't.clientX > 24 || view === "session") return;' in PAGE             # navDrag — не в сессии
    assert 'view !== "session" || split() || FOCUS' in PAGE        # backDrag — только в сессии на телефоне


def test_e2e_motion_demo():
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
    e2e = Path(__file__).resolve().parent / "e2e" / "motion_demo.py"
    spec = importlib.util.spec_from_file_location("motion_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
