"""Точечное обновление списка и ленты (план UX, пункт 1): разметка панели и сценарий в браузере.

Статически: список, проекты и лента обновляются через morph (ключи data-id/data-i/data-proj), шапка — через setHTML;
прямой перерисовки innerHTML у них нет. В браузере (есть Chrome) — tests/e2e/diff_demo.py: без изменений DOM не
трогается, новый ответ — один новый узел с анимацией, изменённый — заменён без анимации.
"""

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html"


def test_lists_use_morph():
    html = WEB.read_text(encoding="utf-8")
    for box in ("sessionsView", "projList", "projChats"):
        assert f'morph($("{box}")' in html, box
        assert f'$("{box}").innerHTML' not in html, box
    assert re.search(r"const fresh = morph\(box, \(histMore", html), "лента — через morph"
    assert 'class="msg ai" data-i="${m.i}"' in html and 'class="msg me" data-i="${m.i}"' in html
    for el in ("title", "target", "rail"):
        assert f'setHTML($("{el}")' in html, el
    assert ".mupd { animation: none !important; }" in html


def test_e2e_diff_demo():
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
    spec = importlib.util.spec_from_file_location("diff_demo", Path(__file__).resolve().parent / "e2e" / "diff_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
