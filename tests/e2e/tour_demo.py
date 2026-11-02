"""Проверка короткого тура в демо панели (Playwright; pytest её не запускает — нужен браузер и сеть до cdnjs).

    python tests/e2e/tour_demo.py http://127.0.0.1:8797/?demo [папка-для-скриншотов]

``&tour=1`` — предложение «Пройти короткий тур?» один раз; «Не сейчас» — больше не предлагается; оба тура проходят
до конца (шаги без элемента на экране пропускаются); «? Подсказать» → «Показать тур по этому экрану»; Esc закрывает
и возвращает фокус; попап не вылезает за экран; без связи с cdnjs — тост «Тур недоступен — нет связи». Ширина 390
и 1366, светлая и тёмная; консоль без ошибок.
"""

import sys


def walk(pg, w: int, shots: str, name: str) -> list[str]:
    """Нажимать «Далее» до конца тура; вернуть заголовки показанных шагов."""
    seen: list[str] = []
    for _ in range(40):
        pg.wait_for_selector(".driver-popover.gp-tour", timeout=8000)
        pg.wait_for_timeout(450)
        title = pg.inner_text(".driver-popover-title")
        box = pg.locator(".driver-popover").bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= w + 0.5, f"{w}px «{title}»: попап за краем {box}"
        if shots and len(seen) < 40:
            pg.screenshot(path=f"{shots}/{name}-{len(seen):02d}.png")
        seen.append(title)
        nxt = pg.inner_text(".driver-popover-next-btn")
        pg.click(".driver-popover-next-btn")
        if nxt == "Готово":
            pg.wait_for_selector(".driver-popover", state="detached")
            return seen
        if nxt == "Дальше":
            pg.wait_for_timeout(600)
    raise AssertionError(f"тур не закончился: {seen}")


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
            tag = f"{w}-{theme}"
            # без &tour=1 демо не предлагает
            pg.goto(f"{base}{sep}theme={theme}")
            pg.wait_for_function("typeof start === 'function' && start.done")
            pg.wait_for_timeout(1800)
            assert not pg.is_visible("#tourOffer"), "предложение без &tour=1"
            # предложение → «Не сейчас» → отметка dismissed, больше не предлагается
            pg.goto(f"{base}{sep}theme={theme}&tour=1")
            pg.wait_for_selector("#tourOffer", timeout=6000)
            if shots:
                pg.screenshot(path=f"{shots}/offer-{tag}.png")
            ob = pg.locator("#tourOffer").bounding_box()
            assert ob["x"] >= 0 and ob["x"] + ob["width"] <= w, f"{w}px: предложение за краем"
            pg.click("#tourOffer .acts [data-tno]")
            assert not pg.is_visible("#tourOffer")
            assert pg.evaluate("demoApi.tour.dev") == "dismissed" and pg.evaluate("tourCache().dev") == "dismissed"
            pg.evaluate("tourOffer.asked = false; tourOffer()")
            pg.wait_for_timeout(500)
            assert not pg.is_visible("#tourOffer"), "после «Не сейчас» предложили снова"
            # отметка только в кэше браузера (сервер демо после перезагрузки пуст) — не предлагаем, переносим на сервер
            pg.goto(f"{base}{sep}theme={theme}&tour=1")
            pg.wait_for_function("typeof start === 'function' && start.done")
            pg.wait_for_timeout(2000)
            assert not pg.is_visible("#tourOffer") and pg.evaluate("demoApi.tour.dev") == "dismissed"
            # предложение → «Пройти» (разработчику): весь тур по экранам
            pg.evaluate("localStorage.clear()")
            pg.goto(f"{base}{sep}theme={theme}&tour=1")
            pg.wait_for_selector("#tourOffer", timeout=6000)
            pg.click("#tourOffer [data-tgo]")
            dev = walk(pg, w, shots, f"dev-{tag}")
            print(tag, "dev:", dev)
            assert "Сессии" in dev and "Строка статуса" in dev and "Интеграции" in dev and dev[-1] == "Настройки"
            # вкладки «Переписка/Экран» — только на широком экране, кнопка «Экран» — только на телефоне; свёрнутого
            # списка нет — шаг пропущен
            assert ("Переписка и экран" in dev) == (w > 900) and ("Экран терминала" in dev) == (w < 900)
            assert "Свёрнутый список" not in dev
            assert pg.evaluate("demoApi.tour.dev") == "done"
            # из меню — для бизнеса
            pg.evaluate("go('go:settings')")
            pg.wait_for_timeout(500)
            pg.get_by_text("Пройти тур: для бизнеса").click()
            biz = walk(pg, w, shots, f"biz-{tag}")
            print(tag, "business:", biz)
            assert biz[0] == "Ваши агенты" and "Примерить на себя" in biz and "Расход" in biz
            assert pg.evaluate("demoApi.tour.business") == "done"
            # «? Подсказать» → «Показать тур по этому экрану»: только шаги экрана; Esc закрывает, фокус — назад
            pg.goto(f"{base}{sep}theme={theme}&open=@3")
            pg.wait_for_function("typeof start === 'function' && start.done")
            pg.wait_for_timeout(800)
            pg.click("#helpBtn")
            pg.wait_for_selector(".help-bg .ha:not(.wait)")
            if shots:
                pg.screenshot(path=f"{shots}/help-{tag}.png")
            pg.click(".help-bg [data-tour-here]")
            pg.wait_for_selector(".driver-popover.gp-tour", timeout=8000)
            pg.wait_for_timeout(400)
            assert pg.inner_text(".driver-popover-progress-text").startswith("Этот экран"), "тур не по экрану"
            if w < 900:                                   # телефон: в сессии нет шагов главной
                assert pg.inner_text(".driver-popover-title") not in ("Ваши агенты", "Сессии, команды, интеграции")
            pg.keyboard.press("Escape")
            pg.wait_for_selector(".driver-popover", state="detached")
            assert pg.evaluate("!tourOn && document.activeElement && document.activeElement.id") == "helpBtn"
            # без связи с cdnjs — тост, ничего не ломается
            pg2 = br.new_page(viewport={"width": w, "height": 800})
            pg2.on("pageerror", lambda e: errs.append(str(e)))
            pg2.route("**/cdnjs.cloudflare.com/ajax/libs/driver.js/**", lambda r: r.abort())
            pg2.goto(f"{base}{sep}theme={theme}")
            pg2.wait_for_function("typeof start === 'function' && start.done")
            pg2.evaluate("void startTour('dev')")
            pg2.wait_for_selector(".toast", timeout=15000)
            assert "Тур недоступен — нет связи" in pg2.inner_text(".toast")
            assert pg2.evaluate("!tourOn") and not pg2.is_visible(".driver-popover")
            pg2.close()
            pg.close()
        br.close()
    errs = [e for e in errs if "driver.js" not in e and "ERR_FAILED" not in e]
    assert not errs, errs
    print("ok: тур — предложение, оба тура, пропуск шагов, «? Подсказать», Esc, без сети; 390/1366, обе темы")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
