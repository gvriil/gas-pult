"""Рабочий стол Ubuntu внутри пульта (#206; Playwright — pytest запускает, только если есть браузер).

    python tests/e2e/desktop_demo.py http://127.0.0.1:8797/?demo

Владелец 14.11: «внутри пульта кнопочка … открыть Ubuntu сразу». Владелец 15.11: «окно с адаптивным дизайном под
размер экрана, с горизонтальной и вертикальной ориентацией и возможностью зума». Демо ``&space=1&home``: кнопка
«Ubuntu» → экран поверх панели; «стол» демо — 1600×900 без сети. Проверяем: вписан по умолчанию (пропорции, весь стол
виден), + / − / 100 % / «Вписать», щипок двумя пальцами и двойной тап («Рука»), поворот — пересчёт без
переподключения, экранная клавиатура, сворачивание кнопок. iPhone 13 (портрет и альбом), iPad, компьютер 1366;
светлая и тёмная; консоль без ошибок. С ``&confirm`` сперва код подтверждения.
"""

import sys

PINCH = """([x, y, d0, d1]) => {
  const p = document.querySelector('.desk-pan'), ev = (t, id, px) => p.dispatchEvent(new PointerEvent(t,
    {pointerId: id, clientX: px, clientY: y, pointerType: 'touch', bubbles: true}));
  ev('pointerdown', 1, x - d0); ev('pointerdown', 2, x + d0);
  for (let k = 1; k <= 5; k++) {
    const d = d0 + (d1 - d0) * k / 5; ev('pointermove', 1, x - d); ev('pointermove', 2, x + d); }
  ev('pointerup', 1, x - d1); ev('pointerup', 2, x + d1); }"""
TAP2 = """([x, y]) => { const p = document.querySelector('.desk-pan'), ev = (t) => p.dispatchEvent(new PointerEvent(t,
  {pointerId: 9, clientX: x, clientY: y, pointerType: 'touch', bubbles: true}));
  ev('pointerdown'); ev('pointerup'); ev('pointerdown'); ev('pointerup'); }"""


def fit_of(pg):
    return pg.evaluate("(() => { const v = document.querySelector('.desk-view'); "
                       "return Math.min(v.clientWidth / 1600, v.clientHeight / 900); })()")


def run(base: str):
    from playwright.sync_api import sync_playwright

    sep = "&" if "?" in base else "?"
    errs: list[str] = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        devs = [("iPhone 13", p.devices["iPhone 13"], "light"), ("iPad", p.devices["iPad (gen 7)"], "dark"),
                ("компьютер", {"viewport": {"width": 1366, "height": 860}}, "dark")]
        for name, dev, th in devs:
            dev = {k: v for k, v in dev.items() if k != "default_browser_type"}
            ctx = br.new_context(**dev, color_scheme=th)
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"{base}{sep}space=1&home&theme={th}")
            pg.wait_for_selector(".sp-desk:visible")
            pg.click(".sp-desk")
            pg.wait_for_function("document.querySelector('.desk-st')?.textContent === 'демо'")
            pg.wait_for_function("window.__deskDemo && window.__deskDemo.fitted")
            vw, vh = pg.viewport_size["width"], pg.viewport_size["height"]
            stage = pg.locator(".desk-stage").bounding_box()
            assert stage["width"] >= vw - 2 and stage["height"] > vh * 0.6, f"{name}: экран не на всё окно {stage}"
            d = pg.evaluate("window.__deskDemo")
            assert abs(d["z"] - fit_of(pg)) < 0.01 and pg.inner_text(".desk-z") == "вписан", f"{name}: не вписан {d}"
            box = pg.locator(".desk-demo").bounding_box()                      # весь стол виден, пропорции 16:9
            assert box["width"] <= vw + 1 and abs(box["width"] / box["height"] - 16 / 9) < 0.02, f"{name}: {box}"
            pg.click("[data-desk=in]")
            z1 = pg.evaluate("window.__deskDemo.z")
            assert z1 > fit_of(pg) and pg.inner_text(".desk-z").endswith("%"), f"{name}: «+» не увеличил"
            pg.click("[data-desk=out]")
            pg.click("[data-desk=one]")
            assert pg.evaluate("window.__deskDemo.z") == 1 and pg.inner_text(".desk-z") == "100 %"
            pg.click("[data-desk=fit]")
            assert pg.evaluate("window.__deskDemo.fitted")
            touch = name != "компьютер"
            assert pg.locator(".desk-pan").is_visible() == touch, f"{name}: «Рука» по умолчанию"
            if not touch:
                pg.click("[data-desk=hand]")                                   # компьютер: включить «Руку» руками
            c = pg.locator(".desk-stage").bounding_box()
            cx, cy = c["x"] + c["width"] / 2, c["y"] + c["height"] / 2
            pg.evaluate(PINCH, [cx, cy, 30, 120])                              # щипок «развести» — увеличить
            assert pg.evaluate("window.__deskDemo.z") > fit_of(pg) * 1.5, f"{name}: щипок не увеличил"
            pg.click("[data-desk=fit]")
            pg.wait_for_timeout(400)
            pg.evaluate(TAP2, [cx, cy])                                        # двойной тап — 100 %
            assert pg.evaluate("window.__deskDemo.z") == 1, f"{name}: двойной тап"
            pg.wait_for_timeout(400)
            pg.evaluate(TAP2, [cx, cy])                                        # ещё раз — вписать
            assert pg.evaluate("window.__deskDemo.fitted"), f"{name}: двойной тап обратно"
            if name != "компьютер":                                            # поворот: альбом и обратно
                pg.set_viewport_size({"width": vh, "height": vw})
                pg.wait_for_timeout(300)
                assert abs(pg.evaluate("window.__deskDemo.z") - fit_of(pg)) < 0.01, f"{name}: поворот не пересчитан"
                assert pg.inner_text(".desk-st") == "демо", "поворот переподключил"
                pg.set_viewport_size({"width": vw, "height": vh})
                pg.wait_for_timeout(300)
            pg.click("[data-desk=kbd]")
            pg.keyboard.type("ls")
            pg.keyboard.press("Enter")
            typed = "".join(pg.evaluate("window.__deskDemo.typed"))
            assert typed == "ls<Enter>", f"{name}: клавиатура {typed}"
            pg.click("[data-desk=tools]")
            assert not pg.locator(".desk-tools").is_visible() and pg.locator("[data-desk=close]").is_visible()
            pg.wait_for_timeout(200)
            assert pg.evaluate("window.__deskDemo.fitted")
            pg.click("[data-desk=close]")
            pg.wait_for_function("!document.querySelector('.desk')")
            ctx.close()
        pg = br.new_page(viewport={"width": 390, "height": 844})               # свежий вход — сперва код
        pg.goto(f"{base}{sep}space=1&home&confirm")
        pg.wait_for_selector(".sp-desk:visible")
        pg.click(".sp-desk")
        pg.wait_for_selector(".sheet-bg")
        assert pg.locator(".desk").count() == 0, "рабочий стол открылся без кода"
        pg.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: рабочий стол — вписан, зум кнопками и щипком, двойной тап, поворот, клавиатура, iPhone/iPad/компьютер")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo")
