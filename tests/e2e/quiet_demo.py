"""Меньше шума (план UX, пункт 9; Playwright; pytest запускает, только если есть браузер).

    python tests/e2e/quiet_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

  (а) нигде нет «обновлено ЧЧ:ММ:СС»; у поля ввода индикатора нет, пока связь есть; шапка и поле ввода не меняются
      от опроса (MutationObserver, 20 с по часам Playwright; «N назад» идёт само);
  (б) нет связи (``&offline``) — плашка «Нет связи» и «нет связи · N с» у поля;
  (в) 1366, главная: «Пульт / хост» справа скрыт — «Пульт» уже в панели чатов; без панели (свёрнута) — виден;
  (г) меню «⋯» панели и строки — глаголы;
  (д) «Удалить» в меню строки — без окна «Вы уверены?»: плашка «Отменить», отмена возвращает строку.
390 и 1366, светлая и тёмная; консоль без ошибок.
"""

import sys

WATCH = """() => { window.__m = 0;
  const mo = new MutationObserver((ms) => { for (const m of ms) {
    const t = m.target.nodeType === 1 ? m.target : m.target.parentElement;
    if (!t.closest('.ago')) window.__m += 1; } });
  const all = { subtree: true, childList: true, characterData: true, attributes: true };
  ['top', 'dock'].forEach((id) => mo.observe(document.getElementById(id), all)); }"""
VERBS = ("Начать", "Создать", "Открыть", "Показать", "Закрепить", "Открепить", "Переименовать", "Удалить")


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for w in (390, 1366):
            for th in ("light", "dark"):
                tag = f"{w} {th}"
                ctx = br.new_context(viewport={"width": w, "height": 860})
                pg = ctx.new_page()
                dialogs: list[str] = []

                def on_dialog(d, box=dialogs):
                    box.append(d.message)
                    d.dismiss()
                pg.on("dialog", on_dialog)
                pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.clock.install()
                pg.goto(f"{base}{sep}open=@1&theme={th}&noscroll")
                pg.clock.run_for(3000)
                pg.wait_for_selector("#content .msg[data-i]")
                # (а)
                assert "обновлено" not in pg.inner_text("body"), f"{tag}: осталось «обновлено …»"
                assert not pg.is_visible("#live"), f"{tag}: индикатор связи виден, хотя связь есть"
                pg.evaluate(WATCH)
                pg.mouse.move(w / 2, 300)
                pg.clock.run_for(20000)
                m = pg.evaluate("() => window.__m")
                assert m <= 4, f"{tag}: шапка и поле ввода меняются от опроса ({m} изменений за 20 с)"
                # (г) «⋯» строки — глаголы, (д) «Удалить» — плашкой
                if w == 1366:
                    pg.click("#navMoreBtn")
                    labels = pg.locator(".pop button span").all_inner_texts()
                    ok = labels and all(x.split()[0] in VERBS for x in labels)
                    assert ok, f"{tag}: «⋯» панели не глаголами: {labels}"
                    pg.keyboard.press("Escape")
                    row = pg.locator("#navList .nrow[data-nw]").first
                    wid = row.get_attribute("data-nw")
                    row.hover()
                    row.locator("[data-nmore]").click()
                    labels = pg.locator(".pop button span").all_inner_texts()
                    assert all(x.split()[0] in VERBS for x in labels), f"{tag}: «⋯» строки не глаголами: {labels}"
                    pg.locator(".pop button", has_text="Удалить").click()
                    pg.wait_for_selector(".toast.undo")
                    asked = dialogs or pg.locator(".sheet-bg").count()
                    assert not asked, f"{tag}: «Удалить» спросило окном: {dialogs}"
                    assert pg.locator(f"#navList .nrow[data-nw='{wid}']").count() == 0, f"{tag}: строка не ушла сразу"
                    if shots:
                        pg.screenshot(path=f"{shots}/quiet-undo-{th}.png")
                    pg.click(".toast.undo button")
                    pg.clock.run_for(1500)
                    back = pg.locator(f"#navList .nrow[data-nw='{wid}']").count()
                    assert back == 1, f"{tag}: «Отменить» не вернуло строку"
                    # (в) дубль заголовка
                    pg.evaluate("() => { current = null; show('home'); setHome('sessions'); }")
                    vis = pg.evaluate("() => getComputedStyle(document.querySelector('#top .titles')).visibility")
                    assert vis == "hidden", f"{tag}: «Пульт / хост» дублирует панель чатов"
                    if shots:
                        pg.screenshot(path=f"{shots}/quiet-home-{th}.png")
                    pg.evaluate("() => document.body.classList.add('side-mini')")
                    pg.clock.run_for(500)
                    vis = pg.evaluate("() => getComputedStyle(document.querySelector('#top .titles')).visibility")
                    assert vis == "visible", f"{tag}: панель свёрнута — заголовок должен быть виден"
                ctx.close()
                # (б) нет связи
                ctx = br.new_context(viewport={"width": w, "height": 860})
                pg = ctx.new_page()
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.clock.install()
                pg.goto(f"{base}{sep}open=@1&offline&theme={th}&noscroll")
                pg.clock.run_for(3000)
                pg.wait_for_selector("#dock:not([hidden])")
                pg.mouse.move(w / 2, 300)
                pg.clock.run_for(25000)
                assert pg.is_visible("#net"), f"{tag}: нет плашки «Нет связи»"
                assert "нет связи" in pg.inner_text("#live"), f"{tag}: у поля нет «нет связи»"
                if shots:
                    pg.screenshot(path=f"{shots}/quiet-offline-{w}-{th}.png")
                ctx.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: меньше шума")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo", sys.argv[2] if len(sys.argv) > 2 else "")
