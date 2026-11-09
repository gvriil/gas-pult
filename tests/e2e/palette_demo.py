"""Палитра Ctrl+K / ⌘K (план UX, пункт 5; Playwright; pytest запускает, только если есть браузер).

    python tests/e2e/palette_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Ctrl+K открывает поиск панели чатов (#149) — он же палитра: в выдаче чаты, проекты и, при запросе, команды
(«Открыть настройки», «Показать экран терминала»…). Enter — первый чат, а если чатов нет — первая команда; стрелки
ходят по строкам. Отдельного второго поиска нет. 390 и 1366, светлая и тёмная; консоль без ошибок.
"""

import sys


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for w in (390, 1366):
            for th in ("light", "dark"):
                tag = f"{w} {th}"
                ctx = br.new_context(viewport={"width": w, "height": 860})
                pg = ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(f"{base}{sep}open=@1&theme={th}&noscroll")
                pg.wait_for_selector("#content .msg[data-i]")
                pg.wait_for_timeout(1200)                        # open=@1 открывает сессию в конце start
                seen = pg.locator("input[type=search]").filter(visible=True).count()
                assert seen == 0, f"{tag}: поиск виден до Ctrl+K"
                pg.keyboard.press("Control+k")
                pg.wait_for_function("() => document.activeElement?.id === 'navQ'", timeout=3000)
                pg.wait_for_timeout(300)                         # телефон: панель выезжает, фокус в поле — через 220 мс
                # команды — по запросу, чаты — по-прежнему
                pg.keyboard.type("экран")
                pg.wait_for_selector("#navList [data-ncmd='screen']")
                assert pg.locator("#navList .nav-sec", has_text="Команды").count() == 1, f"{tag}: нет раздела «Команды»"
                assert pg.locator("#navList [data-nw]").count() == 0, f"{tag}: «экран» нашёл чаты"
                if shots:
                    pg.screenshot(path=f"{shots}/palette-{w}-{th}.png")
                pg.keyboard.press("Enter")                       # чатов нет — первая команда
                pg.wait_for_function("() => tab === 'screen'", timeout=3000)
                # чат по имени — Enter открывает его, команд в выдаче нет
                pg.keyboard.press("Control+k")
                pg.wait_for_function("() => document.activeElement?.id === 'navQ'", timeout=3000)
                pg.wait_for_timeout(300)                         # телефон: панель выезжает, фокус в поле — через 220 мс
                pg.fill("#navQ", "shop")
                pg.wait_for_selector("#navList [data-nw]")
                assert pg.locator("#navList [data-ncmd]").count() == 0, f"{tag}: «shop» нашёл команды"
                wid = pg.get_attribute("#navList [data-nw]", "data-nw")
                pg.keyboard.press("Enter")
                pg.wait_for_function(f"() => current === {wid!r} && view === 'session'", timeout=3000)
                # стрелки — по строкам, Enter на команде
                pg.keyboard.press("Control+k")
                pg.wait_for_function("() => document.activeElement?.id === 'navQ'", timeout=3000)
                pg.wait_for_timeout(300)                         # телефон: панель выезжает, фокус в поле — через 220 мс
                pg.fill("#navQ", "настрой")
                pg.wait_for_selector("#navList [data-ncmd='settings']")
                pg.keyboard.press("ArrowDown")
                at = pg.evaluate("() => document.activeElement?.dataset.ncmd")
                assert at == "settings", f"{tag}: стрелка не на команде ({at})"
                pg.keyboard.press("Enter")
                pg.wait_for_selector(".sheet", timeout=3000)
                assert pg.evaluate("() => NAV.q") == "", f"{tag}: запрос не сброшен после команды"
                ctx.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: палитра Ctrl+K — чаты, проекты и команды")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo", sys.argv[2] if len(sys.argv) > 2 else "")
