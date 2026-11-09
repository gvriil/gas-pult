"""«Закрепить» в демо (Playwright).

    python tests/e2e/pin_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Проект: «⋯» → «Закрепить» — группа «Закреплённые» наверху; долгое нажатие (телефон) или правая кнопка мыши
(компьютер) — то же меню; последний закреплённый — первым. Завершённый чат: «Закрепить» — встаёт наверх
«Завершённых». Вкладка «Сессии»: «Закрепить» и «Открепить». Ширина 390 и 1366, светлая и тёмная, консоль без ошибок.
"""

import sys


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for dev, theme in (("phone", "light"), ("pc", "dark"), ("phone", "dark"), ("pc", "light")):
            kw = {"viewport": {"width": 1366, "height": 860}} if dev == "pc" else \
                {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
            ctx = br.new_context(**kw)
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"{base}{sep}home&proj&theme={theme}&noscroll")
            pg.wait_for_selector("#projectsView .card[data-proj]", timeout=5000)

            def sheet_click(text, pg=pg):
                pg.locator(".sheet button", has_text=text).first.click()

            def order(pg=pg):
                return pg.eval_on_selector_all("#projList .card[data-proj]", "els => els.map((e) => e.dataset.proj)")

            pg.click(".card[data-proj='p-books'] [data-proj-more]")
            sheet_click("Закрепить")
            pg.wait_for_function("document.querySelector('#projList .pin-h')")
            assert order()[0] == "p-books", order()
            card = pg.locator(".card[data-proj='p-tgi']")
            if dev == "phone":                                    # долгое нажатие пальцем
                box = card.bounding_box()
                pg.evaluate("""([x, y]) => document.elementFromPoint(x, y).dispatchEvent(new PointerEvent("pointerdown",
                  { bubbles: true, clientX: x, clientY: y, pointerType: "touch" }))""", [box["x"] + 80, box["y"] + 20])
            else:
                card.click(button="right", position={"x": 80, "y": 20})
            pg.wait_for_selector(".sheet h3", timeout=3000)
            sheet_click("Закрепить")
            pg.wait_for_function("document.querySelector('#projList .card[data-proj]').dataset.proj === 'p-tgi'")
            assert order()[:2] == ["p-tgi", "p-books"], order()         # последний закреплённый — первым
            assert not pg.is_visible("#session")                       # долгое нажатие не открыло проект
            if shots:
                pg.screenshot(path=f"{shots}/pin-projects-{dev}-{theme}.png")
            pg.evaluate("openProject('p-tgi', 'done')")
            pg.wait_for_selector(".card.dchat")
            last = pg.locator(".card.dchat").last
            sid = last.get_attribute("data-chat")
            last.locator("[data-chat-more]").click()
            sheet_click("Закрепить")
            pg.wait_for_function(f"document.querySelector('.card.dchat').dataset.chat === '{sid}'")
            if shots:
                pg.screenshot(path=f"{shots}/pin-done-{dev}-{theme}.png")
            pg.evaluate("closeProject(); setMode('sessions'); setHome('sessions'); refresh()")
            pg.wait_for_selector("#sessionsView .card[data-id]")
            pg.evaluate("sessionSheet('@4')")
            sheet_click("Закрепить")
            pg.wait_for_function("document.querySelector('#sessionsView .card[data-id]').dataset.id === '@4'")
            if shots:
                pg.screenshot(path=f"{shots}/pin-sessions-{dev}-{theme}.png")
            pg.evaluate("sessionSheet('@4')")
            sheet_click("Открепить")
            pg.wait_for_function("!document.querySelector('#sessionsView .pin-h')")
            ctx.close()
        br.close()
    assert not errs, errs
    print("pin_demo ok")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
