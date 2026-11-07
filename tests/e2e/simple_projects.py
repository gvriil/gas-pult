"""Простой режим по проектам (задача 49, PR 8 плана; Playwright).

    python tests/e2e/simple_projects.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Имя вверху → «Проекты и чаты»: проекты чипами, чаты выбранного проекта, «Новый чат», «Прошлые чаты» → прошлый чат
(только чтение) → «Продолжить этот чат». Чипы под шапкой — чаты открытого проекта. Ни слов «терминал», «код», ни путей
и папок; русский экран без латиницы, английский — без кириллицы. Ширина 390 и 1366, светлая и тёмная тема.
"""

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("simple_mode", HERE / "simple_mode.py")
sm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sm)

TECH = ("tmux", "терминал", "Terminal", "git", "~/", "/home", "projects/")


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for w in (390, 1366):
            for theme in ("light", "dark"):
                for lang in ("ru", "en"):
                    tag = f"{w}-{theme}-{lang}"
                    pg = br.new_page(viewport={"width": w, "height": 820})
                    pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                    pg.on("pageerror", lambda e: errs.append(str(e)))
                    pg.goto(f"{base}{sep}simple=1&lang={lang}&theme={theme}")
                    pg.wait_for_function("typeof start === 'function' && start.done")
                    pg.wait_for_timeout(800)
                    head = pg.inner_text("#sWho")
                    want = {"ru": "Иконки магазина", "en": "Shop icons"}[lang]
                    assert want in head, f"{tag}: в шапке нет проекта: {head}"
                    pg.click("#sWho")
                    pg.wait_for_selector(".sheet-bg .s-sheet [data-pj]")
                    assert pg.evaluate("helpContext().screen") == "simple.agents"
                    pg.click('.sheet-bg [data-pj="p-books"]')
                    pg.click(".sheet-bg [data-pjpast]")
                    pg.wait_for_selector(".sheet-bg [data-past]")
                    text = pg.inner_text(".sheet-bg .s-sheet")
                    assert all(t not in text for t in TECH), f"{tag}: техника в листе: {text}"
                    sm.check(pg, lang, tag + " проекты")
                    if shots and theme == "light":
                        pg.screenshot(path=f"{shots}/simple-projects-{tag}.png")
                    pg.click(".sheet-bg [data-past] >> nth=0")
                    pg.wait_for_selector(".sheet-bg .s-past .bubble")
                    assert pg.evaluate("helpContext().screen") == "simple.past"
                    assert pg.locator(".sheet-bg [data-resume]").count() == 1
                    sm.check(pg, lang, tag + " прошлый чат")
                    if shots and theme == "light":
                        pg.screenshot(path=f"{shots}/simple-past-{tag}.png")
                    pg.click(".sheet-bg [data-resume]")
                    pg.wait_for_function("!document.querySelector('.sheet-bg .s-sheet')", timeout=5000)
                    pg.close()
        br.close()
    assert not errs, errs
    print("простой режим по проектам: ок (390/1366, светлая/тёмная, ru/en)")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
