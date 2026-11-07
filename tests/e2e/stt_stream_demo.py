"""Голос потоком (задача 46; Playwright — pytest запускает, только если есть браузер).

    python tests/e2e/stt_stream_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Распознавание в демо подменено (``DemoStt``: слово на каждые 0,4 с звука), микрофон — поддельный Chrome.
Полный режим: держим микрофон — текст растёт в поле, пока «говорим», поле видно, кнопки спрятаны; отпустили — итог
в поле меньше чем за 1 с, поле снова можно править. Касание — запись до «Стоп» (текст дописывается к набранному).
Службы нет (``&asr=off``) — та же запись уходит в /api/stt («Распознаю…») и текст всё равно в поле. Простой режим
(кнопка рядом с «Отправить») и фокус — тот же поток. 390 и 1366, светлая и тёмная, консоль без ошибок.
"""

import sys
import time

PHRASE = "Покажи, что изменилось за сегодня"
NO_BAR = "!document.querySelector('.recbar')"


def hold(pg, sel: str, field: str, secs: float = 1.6) -> float:
    """Держать кнопку ``sel``: пока держим — в поле частичный текст. → сколько ждали итог после отпускания, мс."""
    b = pg.locator(sel).bounding_box()
    pg.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    pg.mouse.down()
    pg.wait_for_function(f"document.getElementById('{field}').value.length > 0", timeout=4000)
    assert pg.evaluate(f"document.getElementById('{field}').readOnly"), "во время диктовки поле — только показ"
    assert pg.locator(".recbar.live").is_visible(), "строки записи нет"
    pg.wait_for_timeout(int(secs * 1000))
    t0 = time.perf_counter()
    pg.mouse.up()
    pg.wait_for_function(f"document.getElementById('{field}').value.includes('{PHRASE}') && {NO_BAR}", timeout=3000)
    return (time.perf_counter() - t0) * 1000


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True,
                               args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        for dev, theme in (("phone", "light"), ("pc", "dark"), ("phone", "dark"), ("pc", "light")):
            where = f"{dev} {theme}"
            kw = {"viewport": {"width": 1366, "height": 860}} if dev == "pc" else \
                {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
            ctx = br.new_context(**kw)
            ctx.grant_permissions(["microphone"])

            def page(q, ctx=ctx, theme=theme):
                pg = ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(f"{base}{sep}{q}&theme={theme}&noscroll")
                pg.wait_for_timeout(900)
                return pg

            # полный режим: удержание → текст по мере речи → итог после отпускания
            pg = page("open=@1")
            b = pg.locator("#mic").bounding_box()
            pg.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
            pg.mouse.down()
            pg.wait_for_function("document.getElementById('input').value.split(' ').length >= 2", timeout=4000)
            assert pg.locator("#input").is_visible() and not pg.locator("#ctools").is_visible(), where
            if shots:
                pg.screenshot(path=f"{shots}/stt-hold-{dev}-{theme}.png")
            pg.wait_for_timeout(900)
            t0 = time.perf_counter()
            pg.mouse.up()
            pg.wait_for_function(f"document.getElementById('input').value === '{PHRASE}' && {NO_BAR}", timeout=3000)
            lag = (time.perf_counter() - t0) * 1000
            assert lag < 1000, f"{where}: итог через {lag:.0f} мс"
            assert not pg.evaluate("document.getElementById('input').readOnly") and pg.locator("#ctools").is_visible()
            if shots:
                pg.screenshot(path=f"{shots}/stt-final-{dev}-{theme}.png")

            # касание: запись идёт и после отпускания, «Стоп» — текст дописывается к набранному
            pg.fill("#input", "Привет.")
            pg.click("#mic")
            pg.wait_for_timeout(1500)
            assert pg.locator(".recbar.live").is_visible(), f"{where}: после касания запись остановилась"
            assert pg.input_value("#input").startswith("Привет. Покажи"), pg.input_value("#input")
            pg.click(".recbar .txt")
            pg.wait_for_function(f"document.getElementById('input').value === 'Привет. {PHRASE}'", timeout=3000)
            pg.close()

            # службы нет — запись целиком прежним путём (/api/stt), текст всё равно в поле
            pg = page("open=@1&asr=off")
            b = pg.locator("#mic").bounding_box()
            pg.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
            pg.mouse.down()
            pg.wait_for_selector(".recbar.live", timeout=4000)
            pg.wait_for_timeout(1200)
            pg.mouse.up()
            pg.wait_for_selector(".recbar.stt .msg", timeout=3000)               # «Распознаю…»
            if shots:
                pg.screenshot(path=f"{shots}/stt-fallback-{dev}-{theme}.png")
            pg.wait_for_function(f"document.getElementById('input').value === '{PHRASE}'", timeout=8000)
            pg.close()

            # простой режим: кнопка рядом с «Отправить», тот же поток
            pg = page("simple=1&lang=ru")
            assert pg.locator("#sMic").is_visible(), f"{where}: в простом режиме нет микрофона"
            lag = hold(pg, "#sMic", "sInput")
            assert lag < 1000, f"{where} простой: итог через {lag:.0f} мс"
            assert pg.locator("#sSend").is_visible() and pg.locator("#sMic").is_visible()
            if shots:
                pg.screenshot(path=f"{shots}/stt-simple-{dev}-{theme}.png")
            pg.close()

            # фокус: тот же микрофон и поток
            pg = page("focus")
            lag = hold(pg, "#mic", "input")
            assert lag < 1000, f"{where} фокус: итог через {lag:.0f} мс"
            pg.close()
            ctx.close()
        br.close()
    assert not errs, errs


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    print("ok")
