"""Всплывающее не закрывает поле ввода (задача 26): реестр зоны уведомлений в index.html против стилей и кода.

Геометрию в браузере проверяет tests/e2e/notices_demo.py (Playwright; в CI браузера нет — там пропускается). Здесь —
то, что CI проверяет всегда: каждый элемент с position: fixed либо живёт в зоне уведомлений, либо стоит над нижней
панелью, либо явно в списке исключений; новый всплывающий элемент без записи в реестр и без проверки в e2e не пройдёт.
"""

import importlib.util
import json
import re
import shutil
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from websrc import web_source

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
PAGE = web_source()
CSS = re.sub(r"/\*.*?\*/", "", PAGE[PAGE.index("<style>"):PAGE.index("</style>")], flags=re.S)
SCRIPT = PAGE[PAGE.index("<script>\n"):]
E2E = Path(__file__).resolve().parent / "e2e" / "notices_demo.py"


def registry(name: str) -> list[str]:
    m = re.search(rf"^const {name} = (\[.*?\]);", SCRIPT, re.M)
    assert m, f"нет реестра {name}"
    return json.loads(m.group(1))


NOTICES, ABOVE_DOCK, FIXED_OK = registry("NOTICES"), registry("ABOVE_DOCK"), registry("FIXED_OK")


def rules() -> list[tuple[list[str], str]]:
    """Самые внутренние правила CSS (в @media тоже): ([селекторы], тело)."""
    return [([x.strip() for x in sel.split(",")], body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS)]


def e2e():
    spec = importlib.util.spec_from_file_location("notices_demo", E2E)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_registries_do_not_overlap():
    assert NOTICES and ABOVE_DOCK and FIXED_OK
    assert not set(NOTICES) & (set(ABOVE_DOCK) | set(FIXED_OK))
    assert not set(ABOVE_DOCK) & set(FIXED_OK)


def test_every_fixed_element_is_registered():
    # Новый position: fixed — сначала решить, где он живёт: в зоне уведомлений (тогда без fixed, через notice()),
    # над нижней панелью (ABOVE_DOCK) или это каркас/лист (FIXED_OK).
    fixed = {s for sels, body in rules() if re.search(r"position:\s*fixed", body) for s in sels}
    assert fixed, "не нашли ни одного position: fixed — разбор стилей сломался"
    stray = fixed - set(ABOVE_DOCK) - set(FIXED_OK)
    assert not stray, f"position: fixed вне реестров NOTICES / ABOVE_DOCK / FIXED_OK в index.html: {sorted(stray)}"
    unused = set(FIXED_OK) - fixed
    assert not unused, f"в FIXED_OK то, чего в стилях уже нет: {sorted(unused)}"
    # Всплывающее из зоны своей позиции не задаёт: его место — поток зоны.
    for sels, body in rules():
        if re.search(r"position:\s*(fixed|absolute)", body):
            assert not set(sels) & set(NOTICES), (sels, body)
    # В скрипте fixed — только невидимое служебное (поле для копирования).
    for m in re.finditer(r"[\"'`][^\"'`\n]*position:\s*fixed[^\"'`\n]*[\"'`]", SCRIPT):
        assert "opacity:0" in m.group(0).replace(" ", ""), m.group(0)


def test_notice_zone_is_bounded_by_header_and_dock():
    z = next(body for sels, body in rules() if sels == [".notices"])
    assert re.search(r"position:\s*fixed", z) and "var(--nz-top" in z and "max-height: var(--nz-max" in z
    assert "overflow: hidden" in z                          # не влезло — обрезается, а не наезжает на поле ввода
    place = SCRIPT[SCRIPT.index("function placeNotices"):SCRIPT.index("\n}\n", SCRIPT.index("function placeNotices"))]
    for x in ('"--nz-top"', '"--nz-max"', '"--nz-dock"', '$("dock")', '".s-dock"', '$("homeBar")'):
        assert x in place, x
    fit = SCRIPT[SCRIPT.index("function fitViewport"):SCRIPT.index("\n}\n", SCRIPT.index("function fitViewport"))]
    assert "visualViewport" in fit and "placeNotices()" in fit    # клавиатура открылась — зона пересчитана
    help_rule = next(body for sels, body in rules() if sels == [".help-bg"] and "bottom" in body)
    assert "var(--nz-dock" in help_rule                     # шторка помощника — над нижней панелью


def test_notices_live_in_the_zone():
    zone = PAGE[PAGE.index('<div class="notices" id="notices">'):]
    zone = zone[:zone.index("\n</div>")]
    for sel in NOTICES:
        if sel.startswith("#"):                             # постоянные — в разметке зоны
            assert f'id="{sel[1:]}"' in zone, f"{sel} не в #notices"
            assert PAGE.count(f'id="{sel[1:]}"') == 1
        else:                                               # создаются кодом — только через notice(el)
            made = list(re.finditer(rf'(\w+)\.className = "{re.escape(sel[1:])}["\s]', SCRIPT))
            assert made, f"{sel}: не нашли, где создаётся"
            for m in made:
                rest = SCRIPT[m.end():]
                rest = rest[:re.search(r"\n(?:async )?function |\n}\n", rest).start()]
                assert f"notice({m.group(1)})" in rest, f"{sel} создаётся мимо notice(): {m.group(0)}"
                assert f"document.body.append({m.group(1)})" not in rest, m.group(0)
    assert "function notice(el) { $(\"notices\").append(el)" in SCRIPT


def test_every_registered_popup_is_checked_in_browser():
    # Добавили в реестр — добавьте и в проверку tests/e2e/notices_demo.py (FULL / SIMPLE), иначе геометрию никто
    # не проверит.
    mod = e2e()
    covered = set(mod.FULL["float"]) | set(mod.SIMPLE["float"]) | {".help-bg"}
    assert set(NOTICES) | set(ABOVE_DOCK) <= covered, (set(NOTICES) | set(ABOVE_DOCK)) - covered
    assert {"#input", "#composer", "#dock"} <= set(mod.FULL["guard"])
    assert {"#sInput", ".s-dock"} <= set(mod.SIMPLE["guard"])
    assert mod.KB > 200 and "visualViewport" in mod.FAKE_KB


def test_update_reloads_only_when_safe_and_keeps_draft():
    safe = SCRIPT[SCRIPT.index("function updSafe"):SCRIPT.index("\n}\n", SCRIPT.index("function updSafe"))]
    for x in ('$("input").value', '$("sInput").value', "files.length", "rec", "micBar", ".sheet-bg", "tourOn",
              "view ==="):
        assert x in safe, x
    assert 'addEventListener("visibilitychange", () => { if (!document.hidden) updAuto(); })' in SCRIPT
    reload = SCRIPT[SCRIPT.index("function reloadPanel"):SCRIPT.index("\n}\n", SCRIPT.index("function reloadPanel"))]
    assert "saveDraft(); location.reload();" in reload
    assert 'addEventListener("pagehide", saveDraft)' in SCRIPT
    assert SCRIPT.count("restoreDraft();") == 3          # полный, простой режим и фокус (задача 41)
    later = SCRIPT[SCRIPT.index('$("updLater").onclick'):].split("\n")[0]
    assert "UPD.later = true" in later and '$("updateBar").hidden = true' in later
    assert "position: fixed" not in next(body for sels, body in rules() if sels == [".upd"])
    # Строка обновления — и в простом режиме, на его языке.
    assert not re.search(r"body\.simple-on[^{]*#updateBar", CSS)
    ru = json.loads((WEB / "i18n" / "ru.json").read_text(encoding="utf-8"))
    assert {"upd.text", "upd.go", "upd.later"} <= ru.keys()


def test_e2e_notices_in_browser():
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        e2e().run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
