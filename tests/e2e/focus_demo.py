"""Режим «Фокус» (задача 41; Playwright — pytest запускает, только если есть браузер).

    python tests/e2e/focus_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Владелец: меню сессии → «Создать фокус-ссылку» — шторка со ссылкой (токен после «#»), «Отправить себе в Telegram»,
«Отозвать»; «Новая сессия» → «В фокусе»; «Настройки» → «Фокус-ссылки». Устройство по ссылке (``&focus``): только чат
одной сессии — нет «Назад», «Настроек», переключателя, списка сессий; в меню — «Интеграции» и «Модель», нет «Сессии» и
«Активная»; «Завершить» → «Сессия завершена». Погасшая ссылка (``&focus=gone``) — сразу «Сессия завершена». Ширина 390
и 1366, светлая и тёмная тема, консоль без ошибок.
"""

import sys

VIS = """(sel) => [...document.querySelectorAll(sel)].some((e) => e.offsetParent !== null
  || getComputedStyle(e).position === "fixed" && getComputedStyle(e).display !== "none")"""


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
            ctx.grant_permissions(["clipboard-read", "clipboard-write"])

            def page(q, ctx=ctx, theme=theme):
                pg = ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(f"{base}{sep}{q}&theme={theme}&noscroll")
                pg.wait_for_timeout(900)
                return pg

            # владелец: шторка фокус-ссылки
            pg = page("open=@1")
            pg.evaluate("sessionSheet('@1')")
            pg.locator(".sheet button", has_text="Создать фокус-ссылку").click()
            pg.wait_for_selector("#focusUrl")
            url = pg.inner_text("#focusUrl")
            assert "/#focus=" in url and "?" not in url, f"{where}: токен не после «#»: {url}"
            for t in ("Отправить себе в Telegram", "Скопировать ссылку", "Отозвать эту ссылку"):
                assert pg.locator(".sheet button", has_text=t).count() == 1, f"{where}: нет «{t}»"
            assert pg.evaluate("document.documentElement.scrollWidth - innerWidth") <= 1, f"{where}: шире экрана"
            if shots:
                pg.screenshot(path=f"{shots}/focus-link-{dev}-{theme}.png")
            pg.locator(".sheet button", has_text="Отправить себе в Telegram").click()
            pg.wait_for_timeout(600)
            pg.keyboard.press("Escape")
            pg.evaluate("document.querySelectorAll('.sheet-bg').forEach((b) => b.remove()); newSession()")
            item = pg.locator(".sheet button", has_text="В фокусе")
            assert item.count() == 1, f"{where}: нет «Новая сессия → В фокусе»"
            item.click()
            pg.wait_for_selector("text=Новая сессия в фокусе — в какой папке?")
            assert pg.get_by_text("Из модуля").count() == 0
            pg.evaluate("document.querySelectorAll('.sheet-bg').forEach((b) => b.remove()); focusList()")
            pg.wait_for_selector("text=iPhone · Safari", timeout=3000)
            if shots:
                pg.screenshot(path=f"{shots}/focus-list-{dev}-{theme}.png")
            pg.close()

            # устройство по ссылке: одна сессия, без пульта
            pg = page("focus")
            pg.wait_for_selector("#session:not([hidden])")
            assert pg.evaluate("document.body.classList.contains('focus')"), f"{where}: не режим фокуса"
            for sel in ("#backBtn", "#settingsBtn", "#switchBtn", "#rail", "#homeBar", "#title .caret"):
                assert not pg.evaluate(VIS, sel), f"{where}: видно {sel}"
            assert pg.evaluate("sessions.length") == 1 and pg.evaluate("current") == "@1"
            pg.evaluate("openSwitcher()")
            assert pg.locator(".sheet-bg").count() == 0, f"{where}: переключатель сессий открылся"
            pg.click("#menuBtn")
            for act, want in (("mcp", True), ("models", True), ("close", True), ("switch", False), ("active", False)):
                assert pg.evaluate(VIS, f"#menu [data-act={act}]") == want, f"{where}: меню {act}"
            if shots:
                pg.screenshot(path=f"{shots}/focus-device-{dev}-{theme}.png")
            pg.click("#menu [data-act=mcp]")
            pg.wait_for_selector("text=Интеграции этой сессии")
            pg.evaluate("document.querySelectorAll('.sheet-bg').forEach((b) => b.remove())")
            pg.evaluate("closeSession('@1')")
            pg.wait_for_selector("#focusEnd", timeout=3000)
            assert "Сессия завершена" in pg.inner_text("#focusEnd")
            if shots:
                pg.screenshot(path=f"{shots}/focus-end-{dev}-{theme}.png")
            pg.close()

            pg = page("focus=gone")
            pg.wait_for_selector("#focusEnd", timeout=3000)
            assert "Сессия завершена" in pg.inner_text("#focusEnd")
            pg.close()
            ctx.close()
        br.close()
    assert not errs, f"ошибки консоли: {errs}"


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    print("focus_demo ok")
