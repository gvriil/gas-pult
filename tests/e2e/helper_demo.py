"""Проверка помощника «? Подсказать» в демо панели (Playwright; pytest её не запускает — нужен браузер).

    python tests/e2e/helper_demo.py http://127.0.0.1:8797/?demo [папка-для-скриншотов]

Для каждого действия карты ``go(id)`` должен открыть ожидаемый экран (по ``helpContext().screen``); пилюля
«Подсказать» — в шапке и в каждом открытом листе; шторка помощника (55 % высоты) открывается поверх листа и
возвращает к нему; чипы и «Перейти: …» работают; консоль без ошибок. Ширина 390 и 1366, светлая и тёмная.
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
    "go:settings.legend": "settings.legend", "go:login": "login", "go:demo": "home.sessions",
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
                top = pg.locator(".sheet-bg .hpill.insheet").last if pg.locator(".sheet-bg").count() else None
                assert (top or pg.locator("#helpBtn")).is_visible(), f"{aid}: нет пилюли «Подсказать»"
            # в сессии — пилюля в шапке; шторка — 55 % высоты; поверх листа и возврат к нему
            pg.goto(f"{base}{sep}theme={theme}&open=@3")
            pg.wait_for_function("typeof start === 'function' && start.done")
            pg.wait_for_timeout(800)
            assert pg.is_visible("#helpBtn")
            pg.click("#helpBtn")
            pg.wait_for_selector(".help-bg .ha:not(.wait)")
            hgt = pg.locator(".help-bg .sheet").bounding_box()["height"]
            assert (0.5 * 800 <= hgt <= 0.62 * 800) or hgt == 320, f"{w}px: шторка {hgt}px"
            assert "Сессия" in pg.inner_text(".help-bg .hwhere")
            pg.click(".help-bg [data-close]")
            if shots:
                pg.screenshot(path=f"{shots}/session-{w}-{theme}.png")
            pg.evaluate("$('settingsBtn').onclick()")
            pg.wait_for_timeout(300)
            pg.click(".sheet-bg .hpill.insheet")
            pg.wait_for_selector(".help-bg .ha:not(.wait)")
            assert "Настройки" in pg.inner_text(".help-bg .hwhere")
            if shots:
                pg.screenshot(path=f"{shots}/settings-help-{w}-{theme}.png")
            pg.click(".help-bg .hchips button >> nth=0")
            pg.wait_for_timeout(400)
            pg.click(".help-bg [data-close]")
            assert pg.locator(".sheet-bg").count() == 1, "лист под помощником должен остаться"
            pg.click(".sheet-bg .hpill.insheet")
            pg.wait_for_selector(".help-bg .ha:not(.wait)")
            pg.fill(".help-bg input[name=q]", "сколько стоит")
            pg.press(".help-bg input[name=q]", "Enter")
            pg.wait_for_timeout(500)
            pg.click(".help-bg [data-go] >> nth=0")
            pg.wait_for_timeout(800)
            assert pg.locator(".help-bg").count() == 0
            pg.close()
        # строка статуса: анти-мигание (фаза держится 900 мс) и эскалация через 12 с без изменений
        pg = br.new_page(viewport={"width": 390, "height": 800})
        pg.goto(f"{base}{sep}open=@1")
        pg.wait_for_function("typeof start === 'function' && start.done")
        pg.wait_for_selector("#act:not(.off)")
        flick = pg.evaluate("""async () => {
          const now = Date.now() / 1000, t = () => document.querySelector("#act .t").textContent;
          actBusy = true;                                  // опрос демо не перебивает подставленные фазы
          liveAct = { w: current, phase: "working", text: "Шаг А", since: now }; paintAct();
          while (t() !== "Шаг А") await new Promise((r) => setTimeout(r, 50));
          await new Promise((r) => setTimeout(r, 1000));
          liveAct = { w: current, phase: "working", text: "Шаг Б", since: now }; paintAct();
          const a = document.querySelector("#act .t").textContent;
          liveAct = { w: current, phase: "working", text: "Шаг В", since: now }; paintAct();
          const b = document.querySelector("#act .t").textContent;
          await new Promise((r) => setTimeout(r, 1000));
          const c = t(); actBusy = false;
          return [a, b, c];
        }""")
        assert flick == ["Шаг Б", "Шаг Б", "Шаг В"], flick         # «В» пришло через 0 мс после «Б» — ждёт 900 мс
        pg.wait_for_selector("#actx:not([hidden]) [data-actx=check]", timeout=20000)
        if shots:
            pg.screenshot(path=f"{shots}/status-escalation-390.png")
        pg.wait_for_selector("#actx [data-actx=notify]", timeout=15000)
        pg.close()
        # каталог модулей и экран входа
        pg = br.new_page(viewport={"width": 390, "height": 800})
        pg.goto(f"{base}{sep}modules=uk-debts")
        pg.wait_for_timeout(1200)
        pg.click("#helpBtn")
        pg.wait_for_selector(".help-bg .ha:not(.wait)")
        pg.fill(".help-bg input[name=q]", "какой модуль выбрать")
        pg.press(".help-bg input[name=q]", "Enter")
        pg.wait_for_timeout(500)
        if shots:
            pg.screenshot(path=f"{shots}/module-help-390.png")
        pg.goto(f"{base}{sep}view=login")
        pg.wait_for_timeout(600)
        pg.click("#helpBtn")
        pg.wait_for_selector(".help-bg .ha:not(.wait)")
        assert "Вход" in pg.inner_text(".help-bg .hwhere")
        if shots:
            pg.screenshot(path=f"{shots}/login-help-390.png")
        br.close()
    assert not errs, errs
    print("ok: все переходы открывают свой экран, пилюля «Подсказать» на месте, статус не мигает, консоль без ошибок")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
