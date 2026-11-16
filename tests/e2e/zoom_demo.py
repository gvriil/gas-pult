"""Увеличение ленты как картинки (владелец 16.11: «нужен зум, как будто мы картинку приближаем»; Playwright).

    python tests/e2e/zoom_demo.py http://127.0.0.1:8797/?demo

Компьютер: Ctrl + колесо над лентой (так же приходит щипок трекпада) → лента крупнее, шрифт панели и поле ввода —
прежние, страница целиком не масштабируется; увеличенную ленту двигают вбок; двойной клик — 100 %. Телефон: два
пальца и жест WebKit (iOS Safari и Telegram) → лента крупнее; двойной тап — 100 %. Настройки → «Размер текста»
(A+ / A−) — отдельно, работает как раньше.
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
TAP2 = """([x, y]) => { const el = document.getElementById('content');
  const t = (k) => el.dispatchEvent(new TouchEvent(k, {bubbles: true, cancelable: true,
    touches: k === 'touchend' ? [] : [new Touch({identifier: 9, target: el, clientX: x, clientY: y})]}));
  t('touchstart'); t('touchend'); t('touchstart'); t('touchend'); }"""
GESTURE = """([scale, x, y]) => { const el = document.getElementById('content');
  const ev = (t) => Object.assign(new Event(t, {bubbles: true, cancelable: true}), {scale, clientX: x, clientY: y});
  window.GestureEvent = window.GestureEvent || function () {};      // как в WebKit: есть события жестов
  el.dispatchEvent(ev('gesturestart')); el.dispatchEvent(ev('gesturechange')); el.dispatchEvent(ev('gestureend')); }"""


def box(pg, sel):
    b = pg.locator(sel).bounding_box()
    return round(b["width"]), round(b["height"])


def run(base: str):
    from playwright.sync_api import sync_playwright

    sep = "&" if "?" in base else "?"
    errs: list[str] = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        # компьютер: Ctrl + колесо над лентой
        pg = br.new_page(viewport={"width": 1366, "height": 860})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{base}{sep}open=@1&noscroll")
        pg.wait_for_selector("#content .msg")
        pg.wait_for_function("!!window.zoomFeed", timeout=8000)            # часть js/zoom.js подгрузилась
        inp, top, top_x = box(pg, "#input"), box(pg, "#title"), pg.locator("#top").bounding_box()["x"]
        c = pg.locator("#content").bounding_box()
        pg.mouse.move(c["x"] + c["width"] / 2, c["y"] + 200)
        pg.keyboard.down("Control")
        for _ in range(4):
            pg.mouse.wheel(0, -100)
        pg.keyboard.up("Control")
        pg.wait_for_timeout(200)
        z = pg.evaluate("feedZoom()")
        assert z > 1.5, f"Ctrl+колесо: лента {z}"
        assert pg.evaluate(FZ) == 1, "поменялся размер шрифта, а не масштаб ленты"
        assert box(pg, "#input") == inp and box(pg, "#title") == top, "поле ввода или шапка масштабировались"
        assert pg.evaluate("visualViewport.scale") == 1, "страница целиком масштабировалась"
        assert pg.evaluate("(() => { const s = document.getElementById('scroller'); "
                           "return s.scrollWidth > s.clientWidth + 10; })()"), "увеличенную ленту не сдвинуть вбок"
        pg.evaluate("document.getElementById('scroller').scrollLeft = 300")
        pg.wait_for_timeout(100)
        assert abs(pg.locator("#top").bounding_box()["x"] - top_x) < 2, "шапка уехала вбок вместе с лентой"
        pg.mouse.dblclick(c["x"] + c["width"] / 2, c["y"] + 200)
        assert pg.evaluate("feedZoom()") == 1, "двойной клик не вернул 100 %"
        pg.close()
        # телефон: два пальца, жест WebKit, двойной тап; размер шрифта — отдельно
        ctx = br.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{base}{sep}open=@1&noscroll")
        pg.wait_for_selector("#content .msg")
        pg.wait_for_function("!!window.zoomFeed", timeout=8000)
        inp = box(pg, "#input")
        pg.evaluate(PINCH, [195, 400, 40, 110])                              # развести пальцы — крупнее
        z = pg.evaluate("feedZoom()")
        assert z > 2, f"два пальца: лента {z}"
        assert pg.evaluate(FZ) == 1 and box(pg, "#input") == inp, "масштабировался шрифт или поле ввода"
        pg.wait_for_timeout(400)
        pg.evaluate(TAP2, [195, 400])
        assert pg.evaluate("feedZoom()") == 1, "двойной тап не вернул 100 %"
        pg.evaluate(GESTURE, [1.8, 195, 400])                                # жест WebKit
        assert abs(pg.evaluate("feedZoom()") - 1.8) < 0.01, "gesturechange не увеличил ленту"
        pg.evaluate("zoomFeed(1)")
        pg.click("#settingsBtn")
        pg.locator(".sheet button", has_text="Размер текста").click()
        pg.locator(".sheet button", has_text="A+").click()
        assert pg.evaluate(FZ) > 1, "A+ не увеличил шрифт"
        pg.locator(".sheet button", has_text="По умолчанию").click()
        assert pg.evaluate(FZ) == 1
        ctx.close()
        br.close()
    assert not errs, f"ошибки: {errs}"
    print("ok: лента увеличивается как картинка — Ctrl+колесо, два пальца, жест WebKit; двойной тап — 100 %")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo")
