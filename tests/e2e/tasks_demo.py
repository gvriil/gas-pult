"""Задачи владельца в панели (#203; Playwright — pytest запускает, только если есть браузер).

    python tests/e2e/tasks_demo.py http://127.0.0.1:8797/?demo

Демо ``&space=1&home``: наверху «Задачи» с цветными счётчиками
(подпись «Задачи: N срочно, …») (квадрант 1 матрицы Эйзенхауэра) вместо «Демо и тесты»; список — карточками по
группам «Срочно» (ждёт вас, просрочено), «Сегодня», «Позже», «Сделано» (свёрнуто), сверху — поле «Добавить задачу»;
нажал задачу с командой — открылся её чат и карточка; «Выполнить» — итог; «Отметить
выполненным» — счётчик уменьшился; решение — вариант уходит в чат дословно; «Демо и тесты» — в «Подсказать».
Телефон 390 и компьютер 1366, светлая и тёмная тема, консоль без ошибок. Код списка — часть js/tasks.js.
"""

import sys

SPY = """() => { window.__sent = []; const a = window.api;
  window.api = (p, b, ...r) => { if (p === '/api/send') window.__sent.push(b); return a(p, b, ...r); }; }"""


def run(base: str):
    from playwright.sync_api import sync_playwright

    sep = "&" if "?" in base else "?"
    errs: list[str] = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        for w, h, th in ((390, 844, "dark"), (1366, 860, "light")):
            where = f"{w} {th}"
            pg = br.new_page(viewport={"width": w, "height": h}, color_scheme=th)
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"{base}{sep}space=1&home&theme={th}")
            pg.wait_for_selector("#navTasks[aria-label^='Задачи']", state="attached")   # «Задачи» — строкой в панели
            assert pg.locator("[data-space=demo]").count() == 0, f"{where}: «Демо и тесты» осталось наверху"
            lab = pg.get_attribute("#navTasks", "aria-label")                 # сводка цветом (17.11): подпись — словами
            assert lab.startswith("Задачи: 2 срочно"), lab
            if w < 900:
                pg.evaluate("navOpen(true)")
                pg.wait_for_timeout(400)
            pg.click("#navTasks")
            pg.wait_for_selector(".sheet[data-tasks] .tsk-c")
            titles = pg.locator(".sheet .tsk-c .tsk-t").all_inner_texts()
            groups = pg.locator(".sheet .tsk-c").evaluate_all("(l) => l.map((x) => x.dataset.g)")
            g = dict(zip(titles, groups, strict=True))
            assert g["Выбрать цену пилота для клиента"] == "urgent", f"{where}: ждёт вас — в «Срочно» {g}"
            assert g["Позвонить бухгалтеру про акт сверки"] == "urgent", f"{where}: срок прошёл — срочно {g}"
            assert g["Написать Ивану про доступ"] == "today", f"{where}: в работе — «Сегодня» {g}"
            assert "Проверить PR с задачами" not in titles, f"{where}: «Сделано» свёрнуто по умолчанию"
            assert pg.locator(".sheet .tsk-g[data-fold=done]").count() == 1
            assert pg.locator(".sheet .tsk-c.t-over").count() == 1 and "просрочено" in pg.inner_text(".sheet")
            assert pg.locator(".sheet .tsk-add #tskNew").count() == 1                 # «Добавить задачу» — сверху
            # провалиться: команда → её чат и карточка; «Выполнить» → итог
            pg.locator(".sheet .tsk-c", has_text="Перезапустить панель после выкладки").locator(".tsk-b").click()
            pg.wait_for_function("() => current === '@2' && view === 'session'")
            card = [x.split("\n")[0] for x in pg.locator(".sheet button").all_inner_texts()]
            assert card[card.index("Выполнить") + 1] == "Скопировать команду", f"{where}: нет действия {card}"
            pg.locator(".sheet button").nth(card.index("Выполнить")).click()
            pg.wait_for_selector(".sheet h3:has-text('Команда выполнена')")
            pg.locator(".sheet button", has_text="Отметить задачу выполненной").click()
            pg.wait_for_function("() => tasksInfo.open === 3")
            # владелец 19.11: после действия — снова список задач на том же месте, «Отменить» 5 с (выполненная ушла
            # в свёрнутое «Сделано» — подсвечивать нечего; изменённая открытая — подсвечена, см. ниже)
            pg.wait_for_selector(".sheet[data-tasks] .tsk-c")
            assert pg.locator(".toast .toast-undo").count() == 1, f"{where}: нет «Отменить»"
            # решение: вариант уходит в чат задачи дословно
            pg.locator(".sheet .tsk-c", has_text="Выбрать цену пилота для клиента").locator(".tsk-b").click()
            pg.wait_for_function("() => current === '@1'")
            pg.evaluate(SPY)
            pg.locator(".sheet button", has_text="80 тыс. ₽").click()
            pg.wait_for_function("() => (document.querySelector('#navTasks').getAttribute('aria-label') || '')"
                                 ".startsWith('Задачи: 1 срочно')")
            # квадрант руками через ⋯: «Написать Ивану» → «Срочно и важно» (список уже открыт — остались на месте)
            pg.wait_for_selector(".sheet[data-tasks] .tsk-c")
            pg.locator(".sheet .tsk-c", has_text="Написать Ивану про доступ").locator("[data-more]").click()
            pg.locator(".sheet button", has_text="Срочность и важность").click()
            pg.locator(".sheet button", has_text="Срочно и важно — сделать сейчас").click()
            pg.wait_for_function("() => (document.querySelector('#navTasks').getAttribute('aria-label') || '')"
                                 ".startsWith('Задачи: 2 срочно')")
            pg.wait_for_selector(".sheet[data-tasks] .tsk-c.just", state="attached")      # изменённая — подсвечена
            sent = pg.evaluate("() => window.__sent")
            assert sent and sent[0]["text"] == "80 тыс. ₽" and sent[0]["w"] == "@1", f"{where}: ответ в чат {sent}"
            # «Готово» галочкой прямо в списке
            n = pg.evaluate("tasksInfo.open")
            pg.locator(".sheet .tsk-c", has_text="Написать Ивану про доступ").locator("[data-done]").click()
            pg.wait_for_function(f"() => tasksInfo.open === {n - 1}")
            # быстрое добавление: одна строка + Enter
            pg.fill("#tskNew", "Купить билеты")
            pg.press("#tskNew", "Enter")
            pg.wait_for_selector(".sheet .tsk-c .tsk-t:text-is('Купить билеты')")
            # «Демо и тесты» — в «Подсказать»
            pg.evaluate("() => document.querySelectorAll('.sheet-bg').forEach((x) => x.remove())")
            pg.evaluate("document.getElementById('helpBtn').click()")   # телефон в чате — «Подсказать» в «⋯»
            pg.wait_for_selector("[data-demo-here]")
            pg.click("[data-demo-here]")
            pg.wait_for_selector(".sheet h3:has-text('Демо и тесты')")
            pg.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: задачи владельца — наверху, провалиться в чат, выполнить, решение — в чат дословно")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo")
