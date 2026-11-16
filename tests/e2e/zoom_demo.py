"""Масштаб текста панели жестом (владелец 16.11: «масштаб двумя пальцами … как в ChatGPT»; Playwright).

    python tests/e2e/zoom_demo.py http://127.0.0.1:8797/?demo

Компьютер: Ctrl + колесо (так же приходит щипок трекпада) → текст крупнее, страница целиком не масштабируется.
Телефон: два пальца (касания) и жест WebKit (gesturechange — iOS Safari и Telegram) → текст крупнее. Настройки →
«Размер текста»: A+ / A− / по умолчанию. При 200 % поле ввода — внизу и видно, прокрутки вбок нет (WCAG 1.4.4).
Значение — на устройстве: после перезагрузки то же.
"""

import sys

FZ = "() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--fz')) || 1"
PINCH = """([x, y, d0, d1]) => {
  const el = document.getElementById('content');
  const mk = (id, px) => new Touch({identifier: id, target: el, clientX: px, clientY: y});
  const fire = (t, d) => el.dispatchEvent(new TouchEvent(t, {
    touches: t === 'touchend' ? [] : [mk(1, x - d), mk(2, x + d)], bubbles: true, cancelable: true}));
  fire('touchstart', d0);
  for (let k = 1; k <= 5; k++) fire('touchmove', d0 + (d1 - d0) * k / 5);
  fire('touchend', d1); }"""
GESTURE = """(scale) => { const ev = (t) => Object.assign(new Event(t, {bubbles: true, cancelable: true}), {scale});
  const el = document.getElementById('content');
  window.GestureEvent = window.GestureEvent || function () {};      // как в WebKit: есть события жестов
  el.dispatchEvent(ev('gesturestart')); el.dispatchEvent(ev('gesturechange')); el.dispatchEvent(ev('gestureend')); }"""


def run(base: str):
    from playwright.sync_api import sync_playwright

    sep = "&" if "?" in base else "?"
    errs: list[str] = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        # компьютер: Ctrl + колесо
        pg = br.new_page(viewport={"width": 1366, "height": 860})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{base}{sep}open=@1&noscroll")
        pg.wait_for_selector("#content .msg")
        pg.wait_for_function("!!window.fontSheet", timeout=8000)            # часть js/zoom.js подгрузилась
        pg.mouse.move(700, 400)
        pg.keyboard.down("Control")
        for _ in range(6):
            pg.mouse.wheel(0, -60)
        pg.keyboard.up("Control")
        pg.wait_for_timeout(200)
        assert pg.evaluate(FZ) > 1.2, f"Ctrl+колесо: --fz {pg.evaluate(FZ)}"
        assert pg.evaluate("visualViewport.scale") == 1, "страница целиком масштабировалась"
        pg.close()
        # телефон: два пальца, жест WebKit, настройки, 200 %
        ctx = br.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{base}{sep}open=@1&noscroll")
        pg.wait_for_selector("#content .msg")
        pg.wait_for_function("!!window.fontSheet", timeout=8000)
        pg.evaluate(PINCH, [195, 400, 40, 100])                              # развести пальцы — крупнее
        f1 = pg.evaluate(FZ)
        assert f1 > 1.5, f"два пальца: --fz {f1}"
        pg.evaluate(GESTURE, 0.7)                                            # жест WebKit «свести» — мельче
        assert pg.evaluate(FZ) < f1, "gesturechange не уменьшил"
        pg.evaluate("setFont(FONT.max)")
        assert abs(pg.evaluate(FZ) - 2.0) < 0.01, "максимум — 200 %"
        inp = pg.locator("#input").bounding_box()
        assert inp and inp["y"] + inp["height"] <= 844 and inp["y"] > 500, f"поле ввода при 200 %: {inp}"
        assert pg.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), "прокрутка вбок при 200 %"
        pg.reload()
        pg.wait_for_selector("#content .msg")
        assert abs(pg.evaluate(FZ) - 2.0) < 0.01, "после перезагрузки размер не сохранился"
        pg.evaluate("setFont(FONT.def)")
        pg.click("#settingsBtn")
        pg.locator(".sheet button", has_text="Размер текста").click()
        pg.locator(".sheet button", has_text="A+").click()
        assert pg.evaluate(FZ) > 1, "A+ не увеличил"
        assert "107 %" in pg.inner_text(".sheet h3"), pg.inner_text(".sheet h3")
        pg.locator(".sheet button", has_text="По умолчанию").click()
        assert pg.evaluate(FZ) == 1
        ctx.close()
        br.close()
    assert not errs, f"ошибки: {errs}"
    print("ok: масштаб текста — Ctrl+колесо, два пальца, жест WebKit, A+/A−, 200 % без поломки, сохраняется")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo")
