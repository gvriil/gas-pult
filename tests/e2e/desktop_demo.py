"""Рабочий стол Ubuntu внутри пульта (#206; Playwright — pytest запускает, только если есть браузер).

    python tests/e2e/desktop_demo.py http://127.0.0.1:8797/?demo

Владелец 14.11: «внутри пульта кнопочка … открыть Ubuntu сразу, минуя браузер». Демо ``&space=1&home``: наверху
«Ubuntu» рядом с «Задачи»; нажатие — экран поверх панели с iframe (в демо — заглушка), «Закрыть» — панель на
месте. С ``&confirm`` сперва код подтверждения. 390 и 1366, светлая и тёмная, консоль без ошибок.
"""

import sys


def run(base: str):
    from playwright.sync_api import sync_playwright

    sep = "&" if "?" in base else "?"
    errs: list[str] = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        for (w, h), th in (((390, 844), "light"), ((1366, 860), "dark")):
            pg = br.new_page(viewport={"width": w, "height": h}, color_scheme=th)
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"{base}{sep}space=1&home&theme={th}")
            pg.wait_for_selector(".sp-desk:visible")
            db = pg.locator(".sp-desk").bounding_box()                     # видна целиком (телефон — второй строкой)
            assert db["x"] >= 0 and db["x"] + db["width"] <= w and db["y"] < 160, f"{w}: кнопка не на виду {db}"
            pg.click(".sp-desk")
            pg.wait_for_selector(".desk iframe")
            fb = pg.locator(".desk iframe").bounding_box()
            assert fb["width"] >= w - 2 and fb["height"] > h * 0.75, f"{w}: экран не на всё окно {fb}"
            pg.wait_for_function("document.querySelector('.desk-st').textContent === 'демо'")
            assert "рабочий стол Ubuntu" in pg.frame_locator(".desk iframe").locator("body").inner_text()
            pg.click("[data-desk=close]")
            pg.wait_for_function("!document.querySelector('.desk')")
            assert pg.locator(".sp-tasks").is_visible()
            pg.close()
        pg = br.new_page(viewport={"width": 390, "height": 844})               # свежий вход — сперва код
        pg.goto(f"{base}{sep}space=1&home&confirm")
        pg.wait_for_selector(".sp-desk:visible")
        pg.click(".sp-desk")
        pg.wait_for_selector(".sheet-bg")
        assert pg.locator(".desk").count() == 0, "рабочий стол открылся без кода"
        pg.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: рабочий стол — кнопка рядом с «Задачи», экран внутри пульта, код для свежего входа")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo")
