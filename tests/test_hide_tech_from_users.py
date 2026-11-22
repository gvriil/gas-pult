"""Штаб 21.11 по снимкам 01–03b: пользователь (не режим разработчика) не видит сырого технического — строки лимитов
под полем, «Терминал · 7 строк · Last login…», «Код 24 строки · PASS…», «Выполняет команду: npm…», «прочитано по
ходу работы», служебного имени окна («tgi-0904») в задачах. Разработчику — всё как было."""
import shutil
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
USER = "for (const c of ['dev_terminal','dev_cost_tokens','dev_sessions','dev_models_mcp'])" \
       " document.body.classList.add('nocap-' + c); 0"


def look(user: bool) -> dict:
    from playwright.sync_api import sync_playwright
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome")
            pg = b.new_page(viewport={"width": 390, "height": 844})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
            pg.wait_for_timeout(2500)
            if user:
                pg.evaluate(USER)
            pg.evaluate("openSession('@1'); 0")
            pg.wait_for_selector(".log summary", timeout=8000)
            pg.wait_for_timeout(800)
            logs = "e => e.map(x => x.innerText.replace(/\\s+/g, ' '))"
            out = {"limits": pg.is_visible("#sinfo") and pg.inner_text("#sinfo"),
                   "logs": pg.eval_on_selector_all(".log summary", logs),
                   "act": pg.inner_text("#act .t"), "feed": pg.inner_text("body")}
            pg.evaluate("part('tasks').then(() => tasksOpen()); 0")
            pg.wait_for_selector(".sheet", timeout=5000)
            pg.wait_for_timeout(600)
            out["tasks"] = pg.inner_text(".sheet")
            b.close()
            out["errs"] = errs
            return out
    finally:
        srv.shutdown()


def need():
    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")


def test_user_sees_human_words():
    need()
    o = look(user=True)
    assert not o["limits"] and not o["errs"]
    assert o["logs"] and all(("Технический текст" in x or "Подробный вывод" in x) for x in o["logs"])
    assert not any("Last login" in x or "PASS" in x for x in o["logs"])
    assert "npm" not in o["act"] and "Выполняет команду" not in o["act"]
    assert "прочитано по ходу работы" not in o["feed"] and "доставлено" in o["feed"]
    assert "tgi-0904" not in o["tasks"] and "из чата «Тесты комнат и сверка П8»" in o["tasks"]   # 21.11: карточка


def test_developer_keeps_raw():
    need()
    o = look(user=False)
    assert "Лимит на неделю" in (o["limits"] or "")
    assert any("Терминал" in x and "Last login" in x for x in o["logs"])
    assert o["act"] not in ("Выполняет действие", "Думает", "Читает документ")   # сырой текст хода, не словарь
    assert "прочитано по ходу работы" in o["feed"]


def test_limits_form_moved_to_part():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'const limitsForm = () => part("limits").then((m) => m.open());' in page
    assert "export async function open()" in (WEB / "js/limits.js").read_text(encoding="utf-8")
