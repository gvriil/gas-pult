"""После клавиатуры на iPhone не остаётся белой полосы (владелец 16.11; Playwright, Chromium с подменой iOS).

    python tests/e2e/keyboard_gap_demo.py http://127.0.0.1:8797/?demo

iOS (Telegram, Safari): клавиатура закрылась, а ``visualViewport`` ещё «с клавиатурой» и событий больше не шлёт —
каркас (--app-h) оставался на высоте с клавиатурой, внизу — белая треть экрана. Подменяем ``visualViewport`` так же:
фокус в поле → высота 500 и событие resize; уход фокуса → высота НЕ меняется и событий нет. Ждём: каркас снова на всю
высоту окна, фон под ним — цвет темы, а не белый.
"""

import sys

import _onebrowser  # noqa: F401  — e2e с браузером по одному на сервер (tests/heavy_lock.py)

FAKE_VV = """(() => {
  const vv = new EventTarget();
  let h = null;                                 // пока тест не задал — как у браузера (innerHeight)
  Object.defineProperty(vv, "height", { get: () => h ?? innerHeight, set: (x) => { h = x; } });
  vv.width = innerWidth; vv.offsetTop = 0; vv.offsetLeft = 0; vv.scale = 1;
  Object.defineProperty(window, "visualViewport", { value: vv, configurable: true });
  window.__vv = vv;
})()"""


def run(base: str):
    from playwright.sync_api import sync_playwright

    sep = "&" if "?" in base else "?"
    errs: list[str] = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        for th in ("dark", "light"):
            pg = br.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, color_scheme=th)
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.add_init_script(FAKE_VV)
            pg.goto(f"{base}{sep}open=@1&noscroll&theme={th}")
            pg.wait_for_selector("#content .msg")
            app_h = "() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--app-h'))"
            full = pg.evaluate("innerHeight")
            assert pg.evaluate(app_h) == full, f"при загрузке: {pg.evaluate(app_h)} ≠ {full}"
            pg.focus("#input")                                       # клавиатура открылась
            pg.evaluate("() => { __vv.height = Math.round(innerHeight * 0.6); "
                        "__vv.dispatchEvent(new Event('resize')); }")
            assert pg.evaluate(app_h) == round(full * 0.6), "с клавиатурой — над ней"
            pg.evaluate("() => document.getElementById('input').blur()")   # закрылась; iOS: 500 и тишина
            pg.wait_for_timeout(1400)
            got = pg.evaluate(app_h)
            assert got == full, f"{th}: после клавиатуры каркас не на весь экран: {got} ≠ {full}"
            bg = pg.evaluate("getComputedStyle(document.documentElement).backgroundColor")
            assert bg not in ("rgba(0, 0, 0, 0)", "rgb(255, 255, 255)") or th == "light", f"фон под каркасом: {bg}"
            pg.close()
        br.close()
    assert not errs, f"ошибки: {errs}"
    print("ok: после клавиатуры каркас — на весь экран, белой полосы нет")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo")
