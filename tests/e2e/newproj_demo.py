"""«Новый проект» в панели чатов (Playwright; pytest запускает, только если есть браузер).

    python tests/e2e/newproj_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Компьютер (1366) и телефон (390), светлая и тёмная тема:
- у заголовка «Проекты» в панели чатов — «+»; лист «Новый проект» (помощник знает экран sheet.new-project);
- «Магазин книг» → папка «magazin-knig» подставляется сама; модель по умолчанию — выбором;
- занятое имя папки — понятная ошибка, лист остаётся открытым, ничего не создано;
- «Создать» → POST /api/project/new и сразу пустой «Новый чат» в этом проекте: окно не запускается
  (/api/project/session не вызывается), проект — в панели чатов;
- наблюдателю «+» нет. Консоль без ошибок.
"""

import sys

COUNT = """() => {
  window.__calls = [];
  const orig = demoApi;
  demoApi = (path, body) => { window.__calls.push([path.split("?")[0], body || null]); return orig(path, body); };
}"""
CALLS = "(p) => window.__calls.filter((c) => c[0] === p)"


def one(br, base: str, sep: str, w: int, mob: bool, th: str, shots: str, errs: list):
    tag = f"{w} {th}"
    ctx = br.new_context(viewport={"width": w, "height": 860}, is_mobile=mob, has_touch=mob)
    pg = ctx.new_page()
    pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"{base}{sep}home&theme={th}&noscroll")
    pg.wait_for_selector("#navList [data-nnewp]", state="attached", timeout=10000)
    pg.evaluate("() => { try { localStorage.setItem('gp:tourDone', '1'); } catch (e) {} }")
    pg.evaluate(COUNT)
    if mob:
        pg.click("#navBtn")
        pg.wait_for_timeout(300)
    plus = pg.locator("#navList [data-nnewp]")
    head = pg.locator("#navList .nav-sec.has-add")
    assert "Проекты" in head.inner_text(), f"{tag}: «+» не у заголовка «Проекты»"
    hb, pb = head.bounding_box(), plus.bounding_box()
    assert pb["x"] + pb["width"] > hb["x"] + hb["width"] - 8, f"{tag}: «+» не справа от заголовка"
    if shots:
        pg.locator("#nav").screenshot(path=f"{shots}/newproj-nav-{w}-{th}.png")
    plus.click()
    pg.wait_for_selector("#npName", state="visible")
    assert pg.evaluate("() => document.querySelector('.sheet-bg').dataset.help") == "sheet.new-project"
    pg.fill("#npName", "Магазин книг")
    assert pg.input_value("#npFolder") == "magazin-knig", f"{tag}: папка из названия {pg.input_value('#npFolder')!r}"
    pg.fill("#npInstr", "Отвечай коротко.")
    pg.click("[data-npm='sonnet']")
    assert pg.get_attribute("[data-npm='sonnet']", "aria-pressed") == "true"
    assert pg.get_attribute("[data-npm='']", "aria-pressed") == "false"
    pg.fill("#npFolder", "gas-pult")                                  # занято — ошибка, лист открыт
    pg.click("#npOk")
    pg.wait_for_selector("#npErr:not([hidden])")
    assert "уже есть" in pg.inner_text("#npErr"), f"{tag}: {pg.inner_text('#npErr')!r}"
    assert pg.locator("#npName").is_visible()
    if shots:
        pg.screenshot(path=f"{shots}/newproj-sheet-{w}-{th}.png")
    pg.fill("#npName", "Магазин книг")
    pg.fill("#npFolder", "")                                            # пусто — снова из названия
    pg.fill("#npName", "Магазин книг 2")
    assert pg.input_value("#npFolder") == "magazin-knig-2"
    pg.click("#npOk")
    pg.wait_for_selector("#content .draft", state="visible", timeout=5000)
    assert pg.locator("#npName").count() == 0, f"{tag}: лист не закрылся"
    calls = pg.evaluate(CALLS, "/api/project/new")
    assert len(calls) == 2 and calls[-1][1] == {"name": "Магазин книг 2", "folder": "magazin-knig-2",
                                                "instructions": "Отвечай коротко.", "model": "sonnet"}, calls
    assert pg.evaluate("() => DRAFT && DRAFT.proj") == "p-new-magazin-knig-2", f"{tag}: новый чат не в проекте"
    assert pg.evaluate(CALLS, "/api/project/session") == [], f"{tag}: окно запущено до первой отправки"
    if mob:
        pg.click("#navBtn")
        pg.wait_for_timeout(300)
    assert pg.locator("#navList .nrow.proj", has_text="Магазин книг 2").count() == 1, f"{tag}: проекта нет в панели"
    if shots:
        pg.screenshot(path=f"{shots}/newproj-draft-{w}-{th}.png")
    ctx.close()

    ctx = br.new_context(viewport={"width": w, "height": 860}, is_mobile=mob, has_touch=mob)   # наблюдатель
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"{base}{sep}home&theme={th}&noscroll&role=viewer")
    pg.wait_for_selector("#navList .nrow", state="attached", timeout=10000)
    assert pg.locator("#navList [data-nnewp]").count() == 0, f"{tag}: «+» у наблюдателя"
    ctx.close()
    print(f"{tag}: ок")


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for w, mob in ((1366, False), (390, True)):
            for th in ("light", "dark"):
                one(br, base, sep, w, mob, th, shots, errs)
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: «Новый проект» из панели чатов")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo", sys.argv[2] if len(sys.argv) > 2 else "")
