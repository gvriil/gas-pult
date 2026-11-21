"""Верхняя полоса и цвета задач (владелец 17.11): на телефоне — одна строка; «Моё пространство» у владельца не
показывается; сводка задач цветом: красный — срочно, оранжевый — ждут вас, жёлтый — в работе; в списке задач —
цветная точка статуса, выполненные — зелёные. Сервер: в сводке — «в работе» (doing)."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import tasks

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"


def test_open_count_has_doing(tmp_path):
    t = tasks.Tasks(tmp_path / "tasks.json")
    for title, st in (("а", "doing"), ("б", "waiting"), ("в", "done")):
        t.add({"title": title, "status": st, "next": "проверить"})
    c = t.open_count()
    assert c["open"] == 2 and c["doing"] == 1 and c["waiting"] == 1


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def test_e2e_topbar_one_row_and_colors():
    sync_api = pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_api.sync_playwright() as p:
            br = p.chromium.launch()
            for w, theme in ((375, "light"), (390, "dark")):
                pg = br.new_page(viewport={"width": w, "height": 760}, is_mobile=True, has_touch=True)
                errs = []
                pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
                pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&space=1&theme={theme}&noscroll")
                pg.wait_for_timeout(1500)
                pg.evaluate("meta.role = 'owner'; meta.desktop = true; meta.tty = true;"
                            " UI = {...(UI || {}), own_space: true}; paintSpaces()")
                bar = pg.evaluate("document.getElementById('spaces').getBoundingClientRect().height")
                assert bar < 45, f"{w}: полоса в две строки ({bar}px)"
                assert pg.evaluate("document.querySelector('.sp-mine').hidden")             # владельцу не показываем
                lab = pg.get_attribute("#navTasks", "aria-label")
                assert "срочно" in lab and "ждут вас" in lab and "в работе" in lab
                dots = pg.evaluate("[...document.querySelectorAll('#navTasks .sdot')].map((e) =>"
                                   " getComputedStyle(e).backgroundColor)")
                assert len(dots) == 3 and len(set(dots)) == 3                           # три разных цвета
                assert pg.get_attribute(".sp-desk:not(.sp-term)", "aria-label") == "Рабочий стол Ubuntu"
                pg.evaluate("navOpen(true)")                                            # телефон: «Задачи» — в панели
                pg.wait_for_timeout(400)
                pg.click("#navTasks")
                pg.wait_for_selector(".sheet .sdot.tq-r", timeout=5000)                 # срочные — красные
                assert pg.locator(".sheet .sdot.tq-o, .sheet .sdot.tq-y").count() >= 1
                assert not errs, errs
                pg.close()
            br.close()
    finally:
        srv.shutdown()
