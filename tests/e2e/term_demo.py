"""Команде нужен ввод — «Открыть в терминале» (задача 47; Playwright).

    python tests/e2e/term_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Под ответом: у команды keepassxc-cli нет «Выполнить», есть «Открыть в терминале» → шторка «Терминал»: экран окна,
поле пароля (скрыто), «Отправить» — экран обновился. Вкладка «Команды»: то же у карточки. Из бота (``&term=@9``) —
шторка сразу. «Настроек → Сервер» (pass) нет. Ширина 390 и 1366, светлая и тёмная тема, консоль без ошибок.
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

            pg = page("open=@1")
            pg.evaluate("renderCmds()")                       # блок «Команды из ответа» (в демо ответ — не последний)
            card = pg.locator(".cmd", has_text="keepassxc-cli")
            card.first.wait_for(timeout=4000)
            assert card.locator("[data-run]").count() == 0, f"{where}: у keepassxc-cli есть «Выполнить»"
            card.locator("[data-term]").click()
            pg.wait_for_selector("#twIn")
            assert pg.get_attribute("#twIn", "type") == "password", f"{where}: пароль виден"
            pg.wait_for_function("document.querySelector('#twScreen').textContent.includes('пароль')", timeout=3000)
            pg.fill("#twIn", "demo-secret")
            pg.click("#twSend")
            pg.wait_for_function("document.querySelector('#twScreen').textContent.includes('код 0')", timeout=4000)
            assert pg.input_value("#twIn") == "", f"{where}: поле пароля не очистилось"
            assert pg.evaluate("document.documentElement.scrollWidth - innerWidth") <= 1, f"{where}: шире экрана"
            if shots:
                pg.screenshot(path=f"{shots}/term-{dev}-{theme}.png")
            pg.click("#twKill")
            assert pg.locator(".termsheet").count() == 0
            pg.evaluate("$('settingsBtn').click()")
            pg.wait_for_timeout(300)
            assert pg.locator(".sheet button", has_text="хранилище паролей").count() == 0, f"{where}: «Сервер» (pass)"
            pg.close()

            pg = page("cmds")
            pg.locator("[data-cterm]").first.wait_for(timeout=4000)
            pg.locator("[data-cterm]").first.click()
            pg.wait_for_selector(".termsheet #twScreen")
            if shots:
                pg.screenshot(path=f"{shots}/term-cmds-{dev}-{theme}.png")
            pg.close()

            pg = page("term=@9")
            pg.wait_for_selector(".termsheet #twScreen", timeout=4000)
            pg.close()
            ctx.close()
        br.close()
    assert not errs, f"ошибки консоли: {errs}"


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    print("term_demo ok")
