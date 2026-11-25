"""Список чатов: строка метаданных и точка «новый ответ» (#189, UI/UX п.7–8; Playwright — pytest запускает,
только если есть браузер).

    python tests/e2e/list_meta_demo.py http://127.0.0.1:8797/?demo&dev [папка-для-снимков]

Демо: под названием @1 — «Opus 5.5 · усилия высокие · контекст 78%»; у @3 новый ответ (журнал сменился с прошлого
просмотра) — точка справа и жирное название, у @1 точки нет. Открыли @3 — точка ушла. Строка не шире панели.
Телефон 390 (панель — по ☰) и компьютер 1366, светлая и тёмная тема, консоль без ошибок.
"""

import sys

import _onebrowser  # noqa: F401  — e2e с браузером по одному на сервер (tests/heavy_lock.py)

SEED = "() => { try { localStorage.setItem('seen:@3:/home/u/projects/gas-pult', 'old'); } catch (e) {} }"


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    sep = "&" if "?" in base else "?"
    errs: list[str] = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        for w, h, th in ((390, 844, "dark"), (1366, 860, "light"), (390, 844, "light"), (1366, 860, "dark")):
            where = f"{w} {th}"
            pg = br.new_page(viewport={"width": w, "height": h}, color_scheme=th)
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.add_init_script(f"({SEED})()")
            pg.goto(f"{base}{sep}home&theme={th}&noscroll")
            pg.wait_for_selector('#navList .nrow[data-nw="@3"]', state="attached")
            pg.evaluate("() => { try { localStorage.setItem('gp:tourDone', '1'); } catch (e) {} }")
            if w < 700:
                pg.click("#navBtn")
                pg.wait_for_timeout(300)
            r1 = pg.locator('#navList .nrow[data-nw="@1"]').first
            meta = r1.get_attribute("title")                              # 20.11: модель и контекст — в подсказке
            assert meta.endswith("Opus 5.5 · усилия высокие · контекст 78%"), f"{where}: {meta!r}"
            assert r1.locator(".nnew").count() == 0, f"{where}: точка у прочитанной"
            r3 = pg.locator('#navList .nrow[data-nw="@3"]').first
            assert r3.locator(".nnew").count() == 1, f"{where}: нет точки «новый ответ»"
            assert r3.locator(".nnew").is_visible(), f"{where}: точка не видна"
            nav = pg.locator("#nav").bounding_box()
            box = r1.bounding_box()
            assert box["x"] + box["width"] <= nav["x"] + nav["width"] + 1, f"{where}: строка шире панели"
            if shots:
                pg.screenshot(path=f"{shots}/list-meta-{w}-{th}.png")
            r3.locator(".nm").click()
            pg.wait_for_function("() => current === '@3'")
            pg.wait_for_function("() => !document.querySelector('#navList .nrow[data-nw=\"@3\"] .nnew')", timeout=15000)
            pg.close()
        br.close()
    assert not errs, errs


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo&dev",
        sys.argv[2] if len(sys.argv) > 2 else "")
    print("ok")
