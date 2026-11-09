"""Панель чатов слева (как в ChatGPT / Claude.ai; Playwright; pytest запускает, только если есть браузер).

    python tests/e2e/nav_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Компьютер (1366) и телефон (390), светлая и тёмная тема:
- «Новый чат» (✎): пустое поле, над ним папка; окно запускается только при первой отправке (/api/project/session),
  затем само сообщение (/api/send);
- «⋯» у строки — меню у самой строки (не шторка снизу), первым «Закрепить»; закреплённое — в «Закреплённые»;
- «Удалить» — строка уходит сразу, «Отменить» 5 с: отменили — на сервер ничего; не отменили — /api/chat/delete;
- телефон: ☰ и свайп от левого края (панель идёт за пальцем), затемнение закрывает; долгое нажатие — меню строки;
- Ctrl+K — поиск по чатам. Консоль без ошибок.
"""

import sys

COUNT = """() => {
  window.__calls = [];
  const orig = demoApi;
  demoApi = (path, body) => { window.__calls.push([path.split("?")[0], body || null]); return orig(path, body); };
}"""
CALLS = "(p) => window.__calls.filter((c) => c[0] === p)"


def touch(cdp, kind, pts):
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [{"x": x, "y": y} for x, y in pts]})


def one(br, base: str, sep: str, w: int, h: int, mob: bool, th: str, shots, errs: list):
    tag = f"{w} {th}"
    ctx = br.new_context(viewport={"width": w, "height": h}, is_mobile=mob, has_touch=mob)
    pg = ctx.new_page()
    pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"{base}{sep}home&theme={th}&noscroll")
    pg.wait_for_selector("#navList .nrow[data-nw]", state="attached")
    pg.evaluate("() => { try { localStorage.setItem('gp:tourDone', '1'); } catch (e) {} }")
    pg.evaluate(COUNT)
    nav = pg.locator("#nav")

    def opened() -> bool:
        pg.wait_for_timeout(260)
        return nav.bounding_box()["x"] > -5

    cdp = ctx.new_cdp_session(pg) if mob else None
    if mob:                                       # телефон: панель спрятана, ☰ открывает, фон закрывает
        assert not opened(), f"{tag}: панель видна без ☰"
        pg.click("#navBtn")
        assert opened(), f"{tag}: ☰ не открыл панель"
        if shots:
            pg.screenshot(path=f"{shots}/nav-open-{w}-{th}.png")
        pg.mouse.click(w - 10, h // 2)
        assert not opened(), f"{tag}: затемнение не закрыло панель"
        touch(cdp, "touchStart", [(4, 420)])    # свайп от края: панель за пальцем, потом открыта
        for x in (30, 70, 120):
            touch(cdp, "touchMove", [(x, 422)])
            pg.wait_for_timeout(30)
        mid = pg.evaluate("() => getComputedStyle(document.getElementById('nav')).transform")
        assert mid.startswith("matrix") and float(mid.split(",")[4]) < -50, f"{tag}: панель не идёт за пальцем ({mid})"
        touch(cdp, "touchMove", [(240, 424)])
        pg.wait_for_timeout(30)
        touch(cdp, "touchEnd", [])
        assert opened(), f"{tag}: свайп от края не открыл панель"
        row = pg.locator("#navList .nrow[data-nw]").first      # долгое нажатие — меню у строки
        b = row.bounding_box()
        touch(cdp, "touchStart", [(b["x"] + 40, b["y"] + b["height"] / 2)])
        pg.wait_for_timeout(650)
        touch(cdp, "touchEnd", [])
        pg.wait_for_selector(".pop", timeout=2000)
        pg.keyboard.press("Escape")
        assert pg.locator(".pop").count() == 0
    else:
        assert opened(), f"{tag}: на компьютере панель слева не видна"
        assert nav.bounding_box()["width"] in range(240, 330), nav.bounding_box()

    def menu(r):                                   # компьютер — «⋯» при наведении, телефон — долгое нажатие
        if not mob:
            r.hover()
            r.locator("[data-nmore]").click()
            return
        bb = r.bounding_box()
        touch(cdp, "touchStart", [(bb["x"] + 40, bb["y"] + bb["height"] / 2)])
        pg.wait_for_timeout(650)
        touch(cdp, "touchEnd", [])

    # «⋯» → меню у строки → «Закрепить»
    row = pg.locator("#navList .nrow[data-nw]").last
    wid = row.get_attribute("data-nw")
    menu(row)
    pop = pg.locator(".pop")
    pop.wait_for()
    rb, pb = row.bounding_box(), pop.bounding_box()
    assert abs(pb["y"] - (rb["y"] + rb["height"])) < 12 or abs(pb["y"] + pb["height"] - rb["y"]) < 12, \
        f"{tag}: меню не у строки ({rb}, {pb})"
    first = pop.locator("button").first.inner_text()
    assert first == "Закрепить", f"{tag}: первым в меню «{first}»"
    if shots:
        pg.screenshot(path=f"{shots}/nav-menu-{w}-{th}.png")
    pop.locator("button").first.click()
    pg.wait_for_function(f"!!document.querySelector(\".nrow.pinned[data-nw='{wid}']\")")
    assert "Закреплённые" in pg.inner_text("#navList")
    assert pg.evaluate(CALLS, "/api/pin")[-1][1]["on"] is True

    # «Удалить» → «Отменить»: на сервер ничего
    def delete(rid: str):
        menu(pg.locator(f"#navList .nrow[data-nw='{rid}']").first)
        pg.locator(".pop button", has_text="Удалить").click()
        pg.wait_for_function(f"!document.querySelector(\"#navList .nrow[data-nw='{rid}']\")")
        pg.wait_for_selector(".toast.undo")

    rid = pg.locator("#navList .nrow[data-nw]:not(.pinned)").first.get_attribute("data-nw")
    delete(rid)
    if shots:
        pg.screenshot(path=f"{shots}/nav-undo-{w}-{th}.png")
    pg.click(".toast.undo button")
    pg.wait_for_selector(f"#navList .nrow[data-nw='{rid}']")
    pg.wait_for_timeout(5500)
    assert not pg.evaluate(CALLS, "/api/chat/delete"), f"{tag}: «Отменить» — а на сервер ушло удаление"
    delete(rid)
    pg.wait_for_timeout(5600)
    dl = pg.evaluate(CALLS, "/api/chat/delete")
    assert len(dl) == 1 and dl[0][1] == {"w": rid}, f"{tag}: удаление не ушло через 5 с: {dl}"

    # Ctrl+K — поиск
    if mob:
        pg.mouse.click(w - 10, h // 2)
        assert not opened()
    pg.keyboard.press("Control+k")
    pg.wait_for_timeout(300)
    assert pg.evaluate("() => document.activeElement.id") == "navQ", f"{tag}: Ctrl+K не открыл поиск"
    name = pg.locator("#navList .nrow[data-nw] .nm").first.inner_text()
    pg.keyboard.type(name[:5])
    pg.wait_for_timeout(100)
    assert all(name[:5].lower() in t.lower() for t in pg.locator("#navList .nrow[data-nw] .nm").all_inner_texts())
    pg.keyboard.press("Escape")

    # ✎ «Новый чат»: окно — только при первой отправке
    if mob and not opened():
        pg.click("#navBtn")
        assert opened()
    pg.click("#navNew")
    pg.wait_for_selector("#content .draft")
    assert pg.is_visible("#draftBar [data-dfold]"), f"{tag}: над полем нет выбора папки"
    assert not pg.evaluate(CALLS, "/api/project/session") and not pg.evaluate(CALLS, "/api/new"), \
        f"{tag}: окно создано до отправки"
    if not mob:
        pg.wait_for_function("() => document.activeElement.id === 'input'", timeout=2000)
    if shots:
        pg.screenshot(path=f"{shots}/nav-new-{w}-{th}.png")
    pg.fill("#input", "Первое сообщение нового чата")
    pg.click("#send")
    pg.wait_for_function("() => view === 'session' && !!current && !DRAFT")
    ses = pg.evaluate(CALLS, "/api/project/session")
    assert len(ses) == 1, f"{tag}: /api/project/session: {ses}"
    pg.wait_for_function("() => window.__calls.some((c) => c[0] === '/api/send')")
    sent = pg.evaluate(CALLS, "/api/send")[0][1]
    assert sent["text"] == "Первое сообщение нового чата", sent
    ctx.close()


def run(base: str, shots: str | None = None):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for w, h, mob in ((1366, 900, False), (390, 844, True)):
            for th in ("light", "dark"):
                one(br, base, sep, w, h, mob, th, shots, errs)
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: панель чатов")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo", sys.argv[2] if len(sys.argv) > 2 else None)
