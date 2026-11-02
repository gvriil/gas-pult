"""Проверка помощника «?» в демо панели (Playwright; pytest её не запускает — нужен браузер).

    python tests/e2e/helper_demo.py http://127.0.0.1:8797/?demo [папка-для-скриншотов]

Для каждого действия карты ``go(id)`` должен открыть ожидаемый экран (по ``helpContext().screen``); кнопка «?» видна
на главной, в сессии, в листах и формах; лист помощника открывается поверх листа и возвращает к нему; чипы и
«Перейти: …» работают; кнопка не перекрывает поле ввода; консоль без ошибок. Ширина 390 и 1366, светлая и тёмная.
"""

import sys

# действие карты → экран, который должен открыться (статический тест сверяет ключи с картой)
DEEP = {
    "go:sessions": "home.sessions", "go:new-session": "sheet.new-session", "go:new-folder": "sheet.new-folder",
    "go:modules": "modules", "go:commands": "home.commands", "go:integrations": "home.integrations",
    "go:models": "home.integrations", "go:voice": "home.integrations", "go:switch": "sheet.switcher",
    "go:session.chat": "session.chat", "go:session.screen": "session.screen", "go:session.menu": "session.menu",
    "go:session.model": "sheet.model", "go:settings": "settings", "go:settings.country": "country",
    "go:settings.cost": "settings.cost", "go:settings.limits": "settings.limits",
    "go:settings.people": "settings.people", "go:settings.setup": "settings.setup",
    "go:settings.legend": "settings.legend", "go:settings.helper": "settings.helper",
    "go:settings.helper-stats": "settings.helper-stats", "go:login": "login", "go:demo": "home.sessions",
}


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for w, theme in ((390, "light"), (1366, "dark"), (390, "dark"), (1366, "light")):
            pg = br.new_page(viewport={"width": w, "height": 800})
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            for aid, want in DEEP.items():
                if aid == "go:demo":
                    continue
                pg.goto(f"{base}{sep}theme={theme}&home=1")
                pg.wait_for_function("typeof start === 'function' && start.done")
                pg.evaluate(f"go({aid!r})")
                pg.wait_for_timeout(900)
                got = pg.evaluate("helpContext().screen")
                assert got == want, f"{w}px {aid}: открылся {got}, ждали {want}"
                assert pg.is_visible("#helpFab"), f"{aid}: нет кнопки «?»"
            # кнопка «?» в сессии не перекрывает поле ввода; лист поверх листа и возврат к нему
            pg.goto(f"{base}{sep}theme={theme}&open=@3")
            pg.wait_for_function("typeof start === 'function' && start.done")
            pg.wait_for_timeout(800)
            fab, comp = pg.locator("#helpFab").bounding_box(), pg.locator("#composer").bounding_box()
            assert fab["y"] + fab["height"] <= comp["y"], f"{w}px: «?» перекрывает поле ввода"
            if shots:
                pg.screenshot(path=f"{shots}/session-{w}-{theme}.png")
            pg.evaluate("$('settingsBtn').onclick()")
            pg.wait_for_timeout(300)
            pg.click("#helpFab")
            pg.wait_for_selector(".help-bg .ha:not(.wait)")
            assert "Настройки" in pg.inner_text(".help-bg .hwhere")
            if shots:
                pg.screenshot(path=f"{shots}/settings-help-{w}-{theme}.png")
            pg.click(".help-bg .hchips button >> nth=0")
            pg.wait_for_timeout(400)
            pg.click(".help-bg [data-close]")
            assert pg.locator(".sheet-bg").count() == 1, "лист под помощником должен остаться"
            pg.click("#helpFab")
            pg.wait_for_selector(".help-bg .ha:not(.wait)")
            pg.fill(".help-bg input[name=q]", "сколько стоит")
            pg.press(".help-bg input[name=q]", "Enter")
            pg.wait_for_timeout(500)
            pg.click(".help-bg [data-go] >> nth=0")
            pg.wait_for_timeout(800)
            assert pg.locator(".help-bg").count() == 0
            pg.close()
        # «умный» ответ для скриншота и экран входа
        pg = br.new_page(viewport={"width": 390, "height": 800})
        pg.goto(f"{base}{sep}help=ai&modules=uk-debts")
        pg.wait_for_timeout(1200)
        pg.click("#helpFab")
        pg.wait_for_selector(".help-bg .ha:not(.wait)")
        pg.fill(".help-bg input[name=q]", "что выбрать для УК?")
        pg.press(".help-bg input[name=q]", "Enter")
        pg.wait_for_selector(".help-bg .hmark.ai")
        if shots:
            pg.screenshot(path=f"{shots}/module-ai-390.png")
        pg.goto(f"{base}{sep}view=login")
        pg.wait_for_timeout(600)
        pg.click("#helpFab")
        pg.wait_for_selector(".help-bg .ha:not(.wait)")
        assert "Вход" in pg.inner_text(".help-bg .hwhere")
        if shots:
            pg.screenshot(path=f"{shots}/login-help-390.png")
        br.close()
    assert not errs, errs
    print("ok: все переходы открывают свой экран, кнопка «?» на месте, консоль без ошибок")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
