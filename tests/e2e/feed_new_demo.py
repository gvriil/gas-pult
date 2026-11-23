"""Разделитель «Новое» в ленте (#189, UI/UX п.5; Playwright — pytest запускает, только если есть браузер).

    python tests/e2e/feed_new_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Демо: прошлый просмотр @3 закончился на сообщении 9 → при открытии «Новое» стоит прямо перед ответом агента 10.
Первое открытие (просмотра не было) — разделителя нет. Ушли и открыли снова — всё прочитано, разделителя нет.
Телефон 390 и компьютер 1366, светлая и тёмная тема, консоль без ошибок.
"""

import sys

import _onebrowser  # noqa: F401  — e2e с браузером по одному на сервер (tests/heavy_lock.py)

SEED = """() => { try { localStorage.setItem('seenI:@3:demo0000', '9'); localStorage.setItem('gp:tourDone', '1'); }
  catch (e) {} }"""
NEXT = """() => { const d = document.querySelector('#content .newdiv'), n = d && d.nextElementSibling;
  return n ? n.className + ' ' + n.dataset.i : null; }"""


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    sep = "&" if "?" in base else "?"
    errs: list[str] = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        for w, h, th in ((390, 844, "dark"), (1366, 860, "light"), (390, 844, "light"), (1366, 860, "dark")):
            where = f"{w} {th}"
            pg = br.new_page(viewport={"width": w, "height": h}, color_scheme=th)
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.add_init_script(f"({SEED})()")
            pg.goto(f"{base}{sep}theme={th}&noscroll")
            pg.wait_for_function("() => typeof openSession === 'function' && sessions.length")
            pg.evaluate("() => openSession('@1')")                     # @1 — впервые: разделителя нет
            pg.wait_for_selector('#content .msg[data-i="10"]')
            assert pg.locator("#content .newdiv").count() == 0, f"{where}: «Новое» без прошлого просмотра"
            pg.evaluate("() => openSession('@3')")
            pg.wait_for_selector("#content .newdiv")
            nxt = pg.evaluate(NEXT)
            assert nxt and "ai" in nxt.split() and nxt.endswith(" 10"), f"{where}: после «Новое» — {nxt}"
            assert pg.inner_text("#content .newdiv").strip().lower() == "новое", f"{where}: подпись"
            if shots:
                pg.locator("#content .newdiv").scroll_into_view_if_needed()
                pg.screenshot(path=f"{shots}/feed-new-{w}-{th}.png")
            pg.evaluate("() => openSession('@1')")
            pg.wait_for_selector('#content .msg[data-i="10"]')
            pg.evaluate("() => openSession('@3')")                     # вернулись — всё прочитано
            pg.wait_for_selector('#content .msg[data-i="10"]')
            pg.wait_for_timeout(300)
            assert pg.locator("#content .newdiv").count() == 0, f"{where}: «Новое» после прочтения"
            pg.close()
        br.close()
    assert not errs, errs


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo", sys.argv[2] if len(sys.argv) > 2 else "")
    print("ok")
