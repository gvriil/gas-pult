"""Карточка вызова инструмента (#258): разрешение Claude Code — внизу переписки карточка с действием, его параметрами
(команда, файл) и «Да» / «Нет»; «Ещё» — остальные пункты. Сервер: humanize.parse отдаёт target, /api/screen — ask."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import humanize

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"

BASH = """
 Bash command

   rm -rf build && npm run build
   Clean and rebuild the project

 Do you want to proceed?
 ❯ 1. Yes
   2. Yes, and don't ask again for npm run build commands in /home/u/p
   3. No, and tell Claude what to do differently (esc)

 Esc to cancel · Tab to amend
"""


def test_target_for_command_file_and_question():
    a = humanize.parse(BASH, target=True)
    assert a["kind"] == "bash" and a["target"] == "rm -rf build && npm run build\nClean and rebuild the project"
    e = humanize.parse(target=True, lines="Edit file\n src/app.py\nDo you want to make this edit to app.py?\n❯ 1. Yes\n"
                       "  2. Yes, allow all edits during this session (shift+tab)\n  3. No, and tell Claude what to do "
                       "differently (esc)\nEsc to cancel")
    assert e["kind"] == "edit" and e["target"] == "app.py"
    q = humanize.parse(target=True, lines="Какой формат?\n❯ 1. PDF\n  2. Word\n  3. Type something\n"
                                         "Enter to select · Esc to cancel")
    assert q and "target" not in q                                      # вопрос агента — без карточки инструмента


def test_screen_api_returns_ask():
    src = (Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "routes" / "sessions.py").read_text(
        encoding="utf-8")                                  # /api/screen — routes/sessions.py (шаг 7)
    assert '"ask": humanize.parse(lines, target=True)' in src
    assert "target" not in humanize.parse(BASH)                     # простой режим (/api/ask) — без имён и команд


def test_e2e_tool_card():
    sync_api = pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_api.sync_playwright() as p:
            br = p.chromium.launch()
            for w, h in ((390, 844), (1366, 860)):
                pg = br.new_page(viewport={"width": w, "height": h})
                errs = []
                pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
                pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&dev&open=@2&tool=bash&noscroll")
                pg.wait_for_selector(".ask.tc", timeout=10000)
                assert "npm run build" in pg.inner_text(".ask.tc .tc-target")
                assert pg.inner_text(".ask.tc .tc-yes") == "Да" and pg.locator(".ask.tc .tc-no").count() == 1
                pg.click(".ask.tc .tc-more")                                 # «Ещё» — остальные пункты
                pg.wait_for_selector(".ask.tc .tc-rest .opt")
                assert "больше не спрашивать" in pg.inner_text(".ask.tc .tc-rest").lower()
                pg.click(".ask.tc .tc-yes")                                  # «Да» — пункт 1, вопрос закрыт
                pg.wait_for_function("!document.querySelector('.ask.tc')", timeout=10000)
                assert not errs, errs
                pg.close()
            br.close()
    finally:
        srv.shutdown()
