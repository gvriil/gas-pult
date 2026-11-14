"""Задачи владельца в панели (#203; Playwright — pytest запускает, только если есть браузер).

    python tests/e2e/tasks_demo.py http://127.0.0.1:8797/?demo

Демо ``&space=1&home``: наверху «Задачи · срочно N» (квадрант 1 матрицы Эйзенхауэра) вместо «Демо и тесты»; список —
по квадрантам (1 сверху, просроченное — срочное), внутри — «ждут вас» первыми,
выполненные — отдельно; нажал задачу с командой — открылся её чат и карточка; «Выполнить» — итог; «Отметить
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
            pg.wait_for_selector(".sp-tasks:has-text('Задачи')")
            assert pg.locator("[data-space=demo]").count() == 0, f"{where}: «Демо и тесты» осталось наверху"
            assert pg.inner_text(".sp-tasks").startswith("Задачи · срочно 2"), pg.inner_text(".sp-tasks")
            pg.click(".sp-tasks")
            pg.wait_for_selector(".sheet h3:has-text('Задачи')")
            labels = [x.split("\n")[0] for x in pg.locator(".sheet button").all_inner_texts()]
            i_wait = labels.index("Выбрать цену пилота для клиента")
            i_cmd = labels.index("Перезапустить панель после выкладки")
            assert i_wait < i_cmd, f"{where}: «ждут вас» не первыми {labels}"
            text = pg.inner_text(".sheet").lower()                           # заголовки групп — прописными (CSS)
            q = [text.index(x) for x in ("срочно и важно", "не разобрано", "срочно, не важно")]
            assert q == sorted(q), f"{where}: квадранты не по порядку {q}"
            i_call = labels.index("Позвонить бухгалтеру про акт сверки")       # срок прошёл — в «срочно и важно»
            assert i_call < labels.index("Написать Ивану про доступ") and "просрочено" in text, f"{where}: {labels}"
            done_i, add_i = labels.index("Проверить PR с задачами"), labels.index("Добавить задачу")
            assert done_i > add_i, f"{where}: выполненные — внизу"
            # провалиться: команда → её чат и карточка; «Выполнить» → итог
            pg.locator(".sheet button", has_text="Перезапустить панель после выкладки").click()
            pg.wait_for_function("() => current === '@2' && view === 'session'")
            card = [x.split("\n")[0] for x in pg.locator(".sheet button").all_inner_texts()]
            assert card[card.index("Выполнить") + 1] == "Скопировать команду", f"{where}: нет действия {card}"
            pg.locator(".sheet button").nth(card.index("Выполнить")).click()
            pg.wait_for_selector(".sheet h3:has-text('Команда выполнена')")
            pg.locator(".sheet button", has_text="Отметить задачу выполненной").click()
            pg.wait_for_function("() => tasksInfo.open === 3")
            # решение: вариант уходит в чат задачи дословно
            pg.click(".sp-tasks")
            pg.wait_for_selector(".sheet h3:has-text('Задачи')")
            pg.locator(".sheet button", has_text="Выбрать цену пилота для клиента").click()
            pg.wait_for_function("() => current === '@1'")
            pg.evaluate(SPY)
            pg.locator(".sheet button", has_text="80 тыс. ₽").click()
            pg.wait_for_function("() => document.querySelector('.sp-tasks').innerText.startsWith('Задачи · срочно 1')")
            # квадрант руками: «Написать Ивану» → «Срочно и важно»
            pg.click(".sp-tasks")
            pg.wait_for_selector(".sheet h3:has-text('Задачи')")
            pg.locator(".sheet button", has_text="Написать Ивану про доступ").click()
            pg.locator(".sheet button", has_text="Срочность и важность").click()
            pg.locator(".sheet button", has_text="Срочно и важно — сделать сейчас").click()
            pg.wait_for_function("() => document.querySelector('.sp-tasks').innerText.startsWith('Задачи · срочно 2')")
            sent = pg.evaluate("() => window.__sent")
            assert sent and sent[0]["text"] == "80 тыс. ₽" and sent[0]["w"] == "@1", f"{where}: ответ в чат {sent}"
            # «Демо и тесты» — в «Подсказать»
            pg.evaluate("() => document.querySelectorAll('.sheet-bg').forEach((x) => x.remove())")
            pg.click("#helpBtn")
            pg.wait_for_selector("[data-demo-here]")
            pg.click("[data-demo-here]")
            pg.wait_for_selector(".sheet h3:has-text('Демо и тесты')")
            pg.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: задачи владельца — наверху, провалиться в чат, выполнить, решение — в чат дословно")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo")
