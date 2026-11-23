"""Счётчик внимания на вкладке и значке (#189, UI/UX п.3; Playwright — pytest запускает, только если есть браузер).

    python tests/e2e/badge_demo.py http://127.0.0.1:8797/?demo

Демо: @2 ждёт ответа, у @3 — новый ответ (журнал сменился с прошлого просмотра) → вкладка «(2) …» и
navigator.setAppBadge(2). Открыли @3 — «(1) …». Телефон 390 и компьютер 1366, светлая и тёмная тема, консоль без ошибок.
"""

import sys

import _onebrowser  # noqa: F401  — e2e с браузером по одному на сервер (tests/heavy_lock.py)

INIT = """() => {
  try { localStorage.setItem('seen:@3:/home/u/projects/gas-pult', 'old'); } catch (e) {}
  window.__badge = [];
  navigator.setAppBadge = (n) => { window.__badge.push(n); return Promise.resolve(); };
  navigator.clearAppBadge = () => { window.__badge.push(0); return Promise.resolve(); };
}"""


def run(base: str):
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
            pg.add_init_script(f"({INIT})()")
            pg.goto(f"{base}{sep}theme={th}")
            pg.wait_for_function("() => document.title.startsWith('(2) ')", timeout=15000)
            got = pg.evaluate("() => window.__badge")
            assert got and got[-1] == 2, f"{where}: значок {got}"
            pg.evaluate("() => openSession('@3')")
            pg.wait_for_function("() => document.title.startsWith('(1) ')", timeout=15000)
            assert pg.evaluate("() => window.__badge.at(-1)") == 1, f"{where}: значок после просмотра"
            pg.close()
        br.close()
    assert not errs, errs


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo")
    print("ok")
