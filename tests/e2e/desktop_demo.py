"""Рабочий стол Ubuntu внутри пульта (#206; Playwright — pytest запускает, только если есть браузер).

    python tests/e2e/desktop_demo.py http://127.0.0.1:8797/?demo

Владелец 14.11: «внутри пульта кнопочка … открыть Ubuntu сразу». Владелец 15.11: «окно с адаптивным дизайном под
размер экрана, с горизонтальной и вертикальной ориентацией и возможностью зума»; «копия не проходит … пароль
неудобно вписывать» — буфер обмена в обе стороны. Демо ``&space=1&home``: кнопка
«Ubuntu» → экран поверх панели; «стол» демо — 1600×900 без сети. Проверяем: вписан по умолчанию (пропорции, весь стол
виден), + / − / 100 % / «Вписать», щипок двумя пальцами и двойной тап («Рука»), поворот — пересчёт без
переподключения, экранная клавиатура, буфер обмена в обе стороны (латиница и кириллица), сворачивание кнопок.
iPhone 13 (портрет и альбом), iPad, компьютер 1366; светлая и тёмная; консоль без ошибок.
С ``&confirm`` сперва код подтверждения.
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


def act(pg, k):
    """Кнопка панели стола: на телефоне она в меню ≡ (владелец 21.11) — сперва открыть меню."""
    if pg.locator(".desk.desk-compact").count() and not pg.locator(".desk-bar").is_visible():
        pg.click(".desk-dock [data-desk=menu]")
    pg.click(f".desk-bar [data-desk={k}]")


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
            ctx = br.new_context(**dev, color_scheme=th, permissions=["clipboard-read", "clipboard-write"])
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
            act(pg, "in")
            z1 = pg.evaluate("window.__deskDemo.z")
            assert z1 > fit_of(pg) and pg.inner_text(".desk-z").endswith("%"), f"{name}: «+» не увеличил"
            act(pg, "out")
            act(pg, "one")
            assert pg.evaluate("window.__deskDemo.z") == 1 and pg.inner_text(".desk-z") == "100 %"
            act(pg, "fit")
            assert pg.evaluate("window.__deskDemo.fitted")
            touch = name != "компьютер"
            pg.evaluate("localStorage.removeItem('gp.desk.ui')")
            assert pg.locator(".desk-pan").is_visible() == touch, f"{name}: «Рука» по умолчанию"
            if not touch:
                act(pg, "hand")                                   # компьютер: включить «Руку» руками
            c = pg.locator(".desk-stage").bounding_box()
            cx, cy = c["x"] + c["width"] / 2, c["y"] + c["height"] / 2
            pg.evaluate(PINCH, [cx, cy, 30, 120])                              # щипок «развести» — увеличить
            assert pg.evaluate("window.__deskDemo.z") > fit_of(pg) * 1.5, f"{name}: щипок не увеличил"
            act(pg, "fit")
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
            # терминал на столе (владелец 15.11: «ввёл пароль, но Enter не работает … Ctrl+C, если мы в терминале»)
            phone = name == "iPhone 13"
            if phone:                                                          # телефон: панель — в меню ≡ (21.11)
                assert pg.locator(".desk.desk-compact").count() == 1, f"{name}: не компактный вид"
                assert not pg.locator(".desk-bar").is_visible() and pg.locator(".desk-dock").is_visible()
                assert not pg.locator(".desk-keys").is_visible(), f"{name}: клавиши на телефоне — по кнопке"
                pg.click(".desk-dock [data-desk=menu]")
                m = pg.locator(".desk-bar").bounding_box()
                assert m["x"] >= 0 and m["y"] >= 0 and m["x"] + m["width"] <= vw and m["y"] + m["height"] <= vh, m
                pg.mouse.click(30, 120)                                        # касание стола — меню закрылось
                assert not pg.locator(".desk-bar").is_visible()
                pg.click(".desk-dock [data-desk=keys]")
                assert pg.locator(".desk-keys").is_visible()
                k = pg.locator(".desk-keys").bounding_box()
                assert k["x"] + k["width"] <= vw and k["y"] + k["height"] <= vh, f"{name}: клавиши за краем {k}"
            else:
                assert pg.locator(".desk.desk-compact").count() == 0 and not pg.locator(".desk-dock").is_visible()
                bar = pg.locator(".desk-bar").bounding_box()
                assert bar["height"] < 48, f"{name}: панель не в одну строку {bar}"
            if touch and not phone:
                assert pg.locator(".desk-keys").is_visible(), f"{name}: ряд клавиш на планшете — по умолчанию"
                assert pg.locator(".desk-pan").is_visible(), "«Рука» включена — а клавиатура всё равно должна работать"
            elif not touch:
                act(pg, "keys")
            act(pg, "kbd")
            pg.keyboard.type("echo ok")
            pg.keyboard.press("Enter")
            assert "$ echo ok\nok\n$ " in pg.evaluate("window.__deskDemo.term"), f"{name}: Enter не выполнил строку"
            pg.keyboard.type("sleep 100")
            pg.evaluate("""() => document.querySelector('.desk-kbd').dispatchEvent(new InputEvent('beforeinput',
                {inputType: 'insertLineBreak', cancelable: true, bubbles: true}))""")      # Enter клавиатуры iOS
            assert pg.evaluate("window.__deskDemo.term").endswith("sleep 100\n"), f"{name}: Enter iOS"
            pg.click(".desk-keys [data-key=c]")                                # Ctrl+C из ряда клавиш
            assert pg.evaluate("window.__deskDemo.term").endswith("^C\n$ "), f"{name}: Ctrl+C"
            pg.click(".desk-keys [data-key='mod:Ctrl']")                       # залипающий Ctrl + буква
            assert pg.get_attribute(".desk-keys [data-key='mod:Ctrl']", "aria-pressed") == "true"
            pg.focus(".desk-kbd")
            pg.keyboard.type("l")
            assert pg.evaluate("window.__deskDemo.typed").pop() == "Ctrl+l" and \
                pg.get_attribute(".desk-keys [data-key='mod:Ctrl']", "aria-pressed") == "false", f"{name}: Ctrl залип"
            pg.click(".desk-keys [data-key=Enter]")
            assert pg.evaluate("window.__deskDemo.typed").pop() == "<Enter>"
            # буфер обмена (владелец 15.11: «копия не проходит … пароль неудобно вписывать»)
            act(pg, "clip")
            pg.fill(".desk-clip-in", "Pa$$w0rd-123")
            pg.click("[data-desk=clip-paste]")
            assert pg.evaluate("window.__deskDemo.typed").pop() == "[вставка]Pa$$w0rd-123", f"{name}: вставка"
            pg.fill(".desk-clip-in", "Пароль-1")                                 # не Latin-1 — набрать клавишами
            pg.click("[data-desk=clip-paste]")
            assert pg.evaluate("window.__deskDemo.typed").pop() == "Пароль-1", f"{name}: кириллица"
            assert pg.input_value(".desk-clip-in") == "", f"{name}: поле не очищено"
            pg.fill(".desk-clip-in", "ёжик")
            pg.click("[data-desk=clip-type]")
            assert pg.evaluate("window.__deskDemo.typed").pop() == "ёжик", f"{name}: «Напечатать»"
            pg.evaluate("window.__deskDemo.copy('https://example.com/секрет')")   # скопировали на столе
            assert pg.locator(".desk-clip-out").is_visible() and "секрет" in pg.inner_text(".desk-clip-text")
            pg.click("[data-desk=clip-copy]")
            assert pg.evaluate("navigator.clipboard.readText()") == "https://example.com/секрет", f"{name}: копия"
            act(pg, "clip")
            if not phone:                                                      # на телефоне вместо «Скрыть» — меню ≡
                act(pg, "hide")                                                # скрыть панель — значок в углу
                assert not pg.locator(".desk-bar").is_visible() and pg.locator(".desk-fab").is_visible()
                pg.wait_for_timeout(200)
                assert pg.evaluate("window.__deskDemo.fitted")
                pg.click(".desk-fab")
                assert pg.locator(".desk-bar").is_visible() and not pg.locator(".desk-fab").is_visible()
            act(pg, "close")
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
