"""Тур фокус-чата и снимок экрана к отчёту об ошибке (задача владельца 23.11: «должны отображаться все функции»).

Тур фокуса — часть js/focustour.js (ядро не растёт); отметки — только в браузере (localStorage по id ссылки):
нового пути для фокус-ссылки нет. Снимок — modern-screenshot с CDN, точная версия и SRI (docs/SECURITY.md, #437).
Браузерный сценарий — tests/e2e/focus_tour_shot_demo.py (WebKit 390 и Chromium 1366; нужен сеть до CDN).
"""

import re
import shutil
import threading
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import access, webapp

WEB = Path(webapp.__file__).resolve().parent / "web"
CORE = (WEB / "index.html").read_text(encoding="utf-8")
TOUR = (WEB / "js/focustour.js").read_text(encoding="utf-8")
BUG = (WEB / "js/bugreport.js").read_text(encoding="utf-8")


def test_core_under_limit_and_tour_item_in_chat_menu():
    assert len(CORE.encode()) < 770000
    item = next(x for x in CORE.splitlines() if 'label: "Тур по экрану"' in x)
    assert 'part("focustour").then((m) => m.start())' in item and "startTour(tourKind(), true)" in item
    assert 'part("focustour").then((m) => m.offer())' in CORE          # предложение — один раз, по ссылке


def test_focus_tour_steps_and_local_marks():
    for t in ("Поле ввода", "Кнопки вариантов", "Сообщить об ошибке", "На другом устройстве", "Чаты", "Меню «⋯»"):
        assert f'title: "{t}"' in TOUR
    assert "loadDriver()" in TOUR and "import " not in TOUR             # driver.js — тот же, из ядра (SRI)
    assert '"gp.ftour:" + (meta?.focus?.id' in TOUR and "/api/" not in TOUR
    assert not re.search(r"[\U0001F300-\U0001FAFF]", TOUR)             # без эмодзи


def test_tour_marks_open_no_new_focus_path():
    """Решение: отметки тура фокуса — только localStorage; /api/tour фокус-ссылке закрыт, как раньше."""
    assert "/api/tour" not in access.FOCUS_GET and "/api/tour" not in access.FOCUS_POST
    assert "/api/tour" not in access.DEMO_GET and "/api/tour" not in access.DEMO_POST


def test_shot_lib_exact_version_with_sri():
    src = re.search(r'src: "(https://[^"]+)"', BUG).group(1)
    assert src == "https://cdn.jsdelivr.net/npm/modern-screenshot@4.7.0/dist/index.js"
    assert re.search(r'sri: "sha512-[A-Za-z0-9+/]{86}=="', BUG)
    assert "integrity: SHOT_LIB.sri" in BUG and 'crossOrigin: "anonymous"' in BUG
    assert "import " not in BUG and '"/api/bug"' in BUG


def test_shot_sheet_texts_mask_and_limits():
    assert "Снимок экрана приложится сам — его можно убрать." in BUG and "Убрать снимок" in BUG
    assert "Поля паролей и кодов на снимке закрыты" in BUG and "Снимок не получился" in BUG
    assert "input[type=password]" in BUG and "one-time-code" in BUG and "[data-no-shot]" in BUG
    assert "SHOT_W = 1280" in BUG and "SHOT_BYTES = 400 * 1024" in BUG and '"image/jpeg"' in BUG
    assert ".sheet-bg" in BUG.split("NOT_IN_SHOT =")[1].split("\n")[0]   # лист отчёта на снимок не попадает


def test_e2e_focus_tour_and_shot():
    import importlib.util

    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    try:
        for u in ("https://cdn.jsdelivr.net/npm/modern-screenshot@4.7.0/dist/index.js",
                  "https://cdnjs.cloudflare.com/ajax/libs/driver.js/1.8.0/driver.min.css"):
            urllib.request.urlopen(urllib.request.Request(u, method="HEAD"), timeout=5).close()
    except Exception:
        pytest.skip("нет связи с CDN — tests/e2e/focus_tour_shot_demo.py с локальными копиями (GP_SHOT_LIB …)")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            p.webkit.launch().close()
        except Exception:
            pytest.skip("нет WebKit для Playwright")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    e2e = Path(__file__).resolve().parent / "e2e" / "focus_tour_shot_demo.py"
    spec = importlib.util.spec_from_file_location("focus_tour_shot_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
