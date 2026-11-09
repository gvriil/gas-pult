"""Подтверждение кодом перед «Выполнить» и терминалом (аудит 09.11; Playwright).

    python tests/e2e/confirm_demo.py "http://127.0.0.1:8797/?demo" [папка-для-снимков]

Демо с ``&confirm`` — новый вход: «Выполнить» у команды открывает шторку «Подтвердите кодом» (код «прислан»),
неверный код — сообщение в шторке, верный (123456) — шторка закрывается и команда выполняется. «Отмена» —
команда не выполняется, у неё ошибка. Без ``&confirm`` — шторки нет. Ширина 390 и 1366, светлая и тёмная тема,
консоль без ошибок.
"""

import sys


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for dev, theme in (("phone", "light"), ("pc", "dark"), ("phone", "dark"), ("pc", "light")):
            where = f"{dev} {theme}"
            kw = {"viewport": {"width": 1366, "height": 860}} if dev == "pc" else \
                {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
            ctx = br.new_context(**kw)

            def page(q, ctx=ctx, theme=theme):
                pg = ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(f"{base}{sep}{q}&theme={theme}&noscroll")
                pg.wait_for_timeout(1200)
                return pg

            def run_btn(pg):
                pg.evaluate("renderCmds()")                   # блок «Команды из ответа» (в демо ответ — не последний)
                btn = pg.locator(".cmd [data-run]:not(.danger)").first
                btn.wait_for(timeout=4000)
                return btn

            pg = page("open=@1&confirm")
            card = run_btn(pg)
            card.click()
            pg.wait_for_selector(".confirm-code #cfCode", timeout=3000)
            pg.wait_for_function("document.querySelector('#cfMsg').textContent.includes('Telegram')", timeout=3000)
            assert pg.locator(".cmd .out-wrap .result").count() == 0, f"{where}: выполнилось до кода"
            pg.fill("#cfCode", "000000")
            pg.wait_for_function("document.querySelector('#cfMsg').textContent.includes('неверный код')", timeout=3000)
            assert pg.locator(".confirm-code").count() == 1, f"{where}: шторка закрылась на неверном коде"
            assert pg.evaluate("document.documentElement.scrollWidth - innerWidth") <= 1, f"{where}: шире экрана"
            if shots:
                pg.screenshot(path=f"{shots}/confirm-{dev}-{theme}.png")
            pg.fill("#cfCode", "123456")
            pg.wait_for_selector(".confirm-code", state="detached", timeout=3000)
            pg.wait_for_selector(".cmd .out-wrap .result.ok", timeout=4000)
            run_btn(pg).click()                               # подтверждено — до конца входа шторки больше нет
            pg.wait_for_timeout(500)
            assert pg.locator(".confirm-code").count() == 0, f"{where}: шторка снова после подтверждения"
            pg.close()

            pg = page("open=@1&confirm")                      # «Отмена» — команда не выполнилась, видна причина
            run_btn(pg).click()
            pg.wait_for_selector(".confirm-code [data-close]")
            pg.click(".confirm-code [data-close]")
            pg.wait_for_selector(".cmd .out-wrap .result.bad", timeout=3000)
            assert "код подтверждения" in pg.locator(".cmd .out-wrap .result.bad").first.text_content()
            pg.close()

            pg = page("open=@1")                              # без &confirm (старый вход) — сразу
            run_btn(pg).click()
            pg.wait_for_selector(".cmd .out-wrap .result.ok", timeout=4000)
            assert pg.locator(".confirm-code").count() == 0, f"{where}: шторка у старого входа"
            pg.close()
            ctx.close()
        br.close()
    assert not errs, f"ошибки консоли: {errs}"
    print("ok: подтверждение кодом — 390/1366, светлая/тёмная")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
