"""Узкая полоса при свёрнутой панели чатов (ПК) в демо (Playwright).

    python tests/e2e/rail_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

1366 светлая и тёмная: панель свёрнута — слева полоса 60 px (не пусто), основная колонка сдвинута на 60 px; сверху
⇥ раскрыть, ✎ новый чат, ⌕ поиск; ниже — проекты квадратами с инициалами (закреплённые — сверху), цифра — активные
чаты, точка — «ждёт ответа»; контраст букв ≥ 4,5:1; нажатие — список чатов проекта у значка, выбранный чат открыт,
его проект — с обводкой; стрелки ходят по значкам; ⌕ раскрывает панель с курсором в поиске; ⇥ — раскрывает; ⚙ —
настройки. Телефон (390) и фокус — без полосы. Консоль без ошибок.
"""

import sys

CONTRAST = """(el) => {
  const rgb = (c) => c.match(/[\\d.]+/g).slice(0, 3).map(Number);
  const ch = (v) => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; };
  const lum = (c) => { const [r, g, b] = rgb(c).map(ch); return .2126 * r + .7152 * g + .0722 * b; };
  const cs = getComputedStyle(el), a = lum(cs.color), b = lum(cs.backgroundColor);
  return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
}"""
INIT = "try { localStorage.setItem('sideMini', '1'); localStorage.setItem('gp:tourDone', '1'); } catch (e) {}"


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for theme in ("light", "dark"):
            tag = f"1366/{theme}"
            ctx = br.new_context(viewport={"width": 1366, "height": 860})
            ctx.add_init_script(INIT)
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"{base}{sep}home&pins&theme={theme}&noscroll")
            pg.wait_for_selector("#rail #railOpen", timeout=8000)
            box = pg.locator("#rail").bounding_box()
            assert box["x"] == 0 and box["width"] == 60, f"{tag}: полоса {box}"
            assert not pg.is_visible("#nav"), f"{tag}: панель чатов не свёрнута"
            top = pg.locator("#top").bounding_box()
            assert abs(top["x"] - 60) < 1, f"{tag}: шапка не сдвинута на ширину полосы ({top})"
            assert not pg.is_visible("#navBtn") and not pg.is_visible("#composeBtn"), f"{tag}: дубль ☰/✎ в шапке"
            ids = pg.eval_on_selector_all("#rail button", "els => els.map((e) => e.id)")
            assert ids == ["railOpen", "railNew", "railSearch", "railSettings"], ids   # 20.11: без значков проектов
            for b in pg.locator("#rail button").all():
                assert b.get_attribute("title") and b.get_attribute("aria-label"), f"{tag}: значок без подсказки"
            if shots:
                pg.screenshot(path=f"{shots}/rail-1366-{theme}.png")
            # пустое место полосы — развернуть, ⇤ — свернуть снова
            gap = pg.locator("#rail .rgap").bounding_box()
            pg.mouse.click(gap["x"] + gap["width"] / 2, gap["y"] + gap["height"] / 2)
            pg.wait_for_timeout(200)
            assert pg.is_visible("#nav") and not pg.is_visible("#rail"), f"{tag}: пустая полоса не развернула"
            pg.click("#sideBtn")
            pg.wait_for_selector("#rail #railOpen", timeout=3000)
            # стрелки по значкам
            pg.focus("#railOpen")
            pg.keyboard.press("ArrowDown")
            assert pg.evaluate("document.activeElement.id") == "railNew", f"{tag}: ↓ не перешла на ✎"
            pg.keyboard.press("End")
            assert pg.evaluate("document.activeElement.id") == "railSettings"
            pg.keyboard.press("ArrowDown")
            assert pg.evaluate("document.activeElement.id") == "railOpen", f"{tag}: ↓ с последнего — не к первому"
            # ⌕ — панель раскрыта, курсор в поиске
            pg.click("#railSearch")
            pg.wait_for_timeout(200)
            assert pg.is_visible("#nav") and not pg.is_visible("#rail"), f"{tag}: ⌕ не раскрыл панель"
            act = pg.evaluate("document.activeElement.id")
            assert act == "navQ", f"{tag}: курсор не в поиске ({act})"
            pg.keyboard.press("Escape")
            pg.click("#sideBtn")                                   # свернуть снова
            pg.wait_for_selector("#rail #railOpen", timeout=3000)
            pg.click("#railOpen")
            assert pg.is_visible("#nav") and not pg.is_visible("#rail"), f"{tag}: ⇥ не раскрыл панель"
            pg.click("#sideBtn")
            pg.wait_for_selector("#railNew")
            pg.click("#railNew")
            pg.wait_for_selector("#content .draft", timeout=3000)
            pg.click("#railSettings")
            pg.wait_for_timeout(400)
            assert pg.evaluate("view") == "settings" or pg.locator(".sheet").count(), f"{tag}: ⚙ не открыл настройки"
            ctx.close()
        # телефон — без полосы (в фокусе полоса есть с #324, без «Новый чат» и «Настройки» — test_focus)
        for q, kw in (("home", {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}),):
            ctx = br.new_context(**kw)
            ctx.add_init_script(INIT)
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"{base}{sep}{q}&theme=dark&noscroll")
            pg.wait_for_timeout(1500)
            assert not pg.is_visible("#rail"), f"{q}: полоса видна"
            ctx.close()
        br.close()
    assert not errs, errs
    print("rail_demo ok")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
