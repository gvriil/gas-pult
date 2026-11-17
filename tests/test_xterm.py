"""Терминал как терминал (владелец 17.11): эмулятор xterm.js в «Живом терминале» — экран с цветами и курсором,
окно tmux под размер области (/api/tty/size), прокрутка до начала подгружает историю, ввод уходит в окно, при
закрытии размер окна возвращается к клиентам tmux. Демо панели; xterm.js — с cdnjs (нет сети — пропуск)."""

import os
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
SHOTS = Path(os.environ.get("GAS_PULT_SHOTS") or tempfile.gettempdir())   # в docs: GAS_PULT_SHOTS=docs/screens


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def test_e2e_xterm_terminal():
    sync_api = pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with sync_api.sync_playwright() as p:
            br = p.chromium.launch()
            for w, h, mob in ((390, 844, True), (1366, 860, False)):
                pg = br.new_page(viewport={"width": w, "height": h}, is_mobile=mob, has_touch=mob)
                errs = []
                pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
                pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo&open=@1&noscroll")
                pg.wait_for_selector("#content .msg")
                pg.evaluate("meta.tty = true; window.__sz = []; window.__api = api; window.api = (...a) => {"
                            " if (a[0] === '/api/tty/size') __sz.push(a[1]); return __api(...a); }; ttyOpen('@1'); 0")
                try:
                    pg.wait_for_selector(".tty .tbox.xt .xterm", timeout=15000)
                except sync_api.TimeoutError:
                    pytest.skip("xterm.js с cdnjs не загрузился (нет сети)")
                pg.wait_for_function("__sz.length > 0", timeout=5000)
                pg.wait_for_timeout(1500)
                st = "document.querySelector('.ttybg').__tty"
                cols, rows = pg.evaluate(f"[{st}.xt.cols, {st}.xt.rows]")
                assert pg.evaluate("__sz.at(-1)") == {"w": "@1", "cols": cols, "rows": rows}   # окно — под область
                buf = f"(() => {{ const b = {st}.xt.buffer.active; return [...Array(b.length).keys()]" \
                      ".map((i) => b.getLine(i).translateToString(true)); })()"
                lines = pg.evaluate(buf)
                assert pg.evaluate(f"{st}.xt.buffer.active.viewportY === {st}.xt.buffer.active.baseY")   # внизу
                assert any(x.startswith("❯") for x in lines[-rows:]), "приглашения нет на экране"
                SHOTS.mkdir(exist_ok=True)
                pg.screenshot(path=str(SHOTS / f"terminal-xterm-{w}.png"))
                # крупнее текст (A+) — меньше колонок, окно tmux пересчитано
                pg.evaluate("document.documentElement.style.setProperty('--fz', '1.5')")
                pg.wait_for_function(f"__sz.at(-1).cols < {cols}", timeout=6000)
                c2, r2 = pg.evaluate(f"[{st}.xt.cols, {st}.xt.rows]")
                assert pg.evaluate("__sz.at(-1)") == {"w": "@1", "cols": c2, "rows": r2} and c2 < cols
                pg.evaluate("document.documentElement.style.setProperty('--fz', '1')")
                pg.wait_for_function(f"__sz.at(-1).cols > {c2}", timeout=6000)          # A− — снова шире
                # прокрутка до начала — страница выше
                n0 = len(lines)
                pg.evaluate(f"{st}.xt.scrollToTop()")
                pg.wait_for_function(f"{st}.xt.buffer.active.length > {n0}", timeout=5000)
                # ввод — в окно (демо отвечает «получено: …»)
                pg.evaluate(f"{st}.xt.scrollToBottom(); {st}.xhold = false; {st}.xt.focus()")
                pg.keyboard.type("ls")
                pg.keyboard.press("Enter")
                pg.wait_for_function(f"{buf}.some((x) => x.includes('получено: ls'))", timeout=8000)
                # закрыли — размер окна снова по клиентам tmux
                pg.click(".sheet.tty [data-close]")
                pg.wait_for_function("__sz.some((x) => x.reset)", timeout=3000)
                assert not errs, errs
                pg.close()
            br.close()
    finally:
        srv.shutdown()
