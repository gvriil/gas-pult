"""Живой терминал (задача 50; Playwright).

    python tests/e2e/tty_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Сессия → «Экран» → «Живой терминал»: лист во весь экран с хвостом истории; прокрутка вверх подгружает строки выше;
поиск находит строку из начала истории и подсвечивает её; ввод с клавиатуры (компьютер — прямо в экран, телефон —
строка ввода и спецклавиши, липкий Ctrl) попадает в окно. «Журнал сессии» — переписка. Нет кнопки у наблюдателя
и в простом режиме. Ширина 390 и 1366, светлая и тёмная тема, консоль без ошибок.
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

            pg = page("open=@3")
            pg.evaluate("setTab('screen')")
            pg.wait_for_selector("#termLive", timeout=4000)
            pg.click("#termLive")
            pg.wait_for_function("document.querySelector('#ttyPre').textContent.includes('❯')", timeout=4000)
            shown = pg.evaluate("document.querySelector('#ttyPre').textContent.split('\\n').length")
            assert shown < 600, f"{where}: сразу показана вся история ({shown})"
            assert "строк в истории" in pg.text_content("#ttySub"), where
            pg.evaluate("document.querySelector('#ttyPre').scrollTop = 0")         # вверх — подгрузка выше
            pg.wait_for_function(f"document.querySelector('#ttyPre').textContent.split('\\n').length > {shown}",
                                 timeout=4000)
            pg.click("#ttyFind")                                                   # поиск по всей истории
            pg.fill("#ttyQ", "круг 2")
            pg.wait_for_function("document.querySelector('#ttyCnt').textContent === '1 из 1'", timeout=4000)
            assert pg.locator("#ttyPre mark.cur").count() == 1, f"{where}: совпадение не подсвечено"
            pg.fill("#ttyQ", "case-")
            pg.wait_for_function("/ из \\d{3,}/.test(document.querySelector('#ttyCnt').textContent)", timeout=4000)
            pg.click("#ttyPrev")
            assert pg.locator("#ttyPre mark.cur").count() == 1
            pg.click("#ttyFind")                                                   # закрыть поиск
            assert "[скрыт: токен GitHub]" in pg.text_content("#ttyPre"), f"{where}: маска секрета"
            if dev == "pc":                                                        # печатаем прямо в экран
                pg.click("#ttyBox")
                pg.keyboard.type("ls -la")
                pg.keyboard.press("Enter")
                pg.wait_for_function("document.querySelector('#ttyPre').textContent.includes('получено: ls -la')",
                                     timeout=4000)
            else:                                                                  # строка ввода и спецклавиши
                assert pg.locator("#ttyKeys [data-k='Escape']").is_visible(), f"{where}: нет спецклавиш"
                pg.fill("#ttyIn", "привет")
                pg.click("#ttySend")
                pg.wait_for_function("document.querySelector('#ttyPre').textContent.includes('получено: привет')",
                                     timeout=4000)
                pg.click("#ttyKeys [data-k='ctrl']")
                assert pg.get_attribute("#ttyKeys [data-k='ctrl']", "aria-pressed") == "true", f"{where}: Ctrl"
                pg.type("#ttyIn", "c")
                pg.wait_for_function("document.querySelector('#ttyPre').textContent.includes('^C')", timeout=4000)
                assert pg.get_attribute("#ttyKeys [data-k='ctrl']", "aria-pressed") == "false", where
                assert pg.input_value("#ttyIn") == "", f"{where}: буква после Ctrl осталась в строке"
            assert pg.evaluate("document.documentElement.scrollWidth - innerWidth") <= 1, f"{where}: шире экрана"
            if shots:
                pg.screenshot(path=f"{shots}/tty-{dev}-{theme}.png")
            pg.click("#ttyMode [data-m='log']")                                    # журнал сессии
            pg.wait_for_function("document.querySelector('#ttyPre').textContent.includes('· вы ──')", timeout=4000)
            if shots:
                pg.screenshot(path=f"{shots}/tty-log-{dev}-{theme}.png")
            pg.click(".tty [data-close]")
            assert pg.locator(".ttybg").count() == 0
            pg.close()

            pg = page("term=@9")                                                   # окно gp-term — тот же лист
            pg.wait_for_selector("#twLive", timeout=4000)
            pg.click("#twLive")
            pg.wait_for_selector(".ttybg #ttyPre")
            assert "gp-term" in pg.text_content("#ttySub") and pg.locator("#ttyMode").is_hidden(), where
            pg.close()

            for q in ("open=@3&role=viewer", "open=@3&simple=1"):                 # наблюдателю и в простом — нет
                pg = page(q)
                pg.evaluate("typeof setTab === 'function' && current && setTab('screen')")
                pg.wait_for_timeout(500)
                assert pg.locator("#termLive").count() == 0, f"{where} {q}: кнопка живого терминала"
                pg.evaluate("ttyOpen('@3')")
                assert pg.locator(".ttybg").count() == 0, f"{where} {q}: лист открылся"
                pg.close()
            ctx.close()
        br.close()
    assert not errs, f"ошибки консоли: {errs}"


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    print("tty_demo ok")
