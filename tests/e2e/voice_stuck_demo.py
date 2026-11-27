"""Голос на iPhone: «закончил говорить, а кнопка ни стоп, ни отправить не нажимается» (жалоба владельца 15.11).

    python tests/e2e/voice_stuck_demo.py http://127.0.0.1:8797/?demo&dev

Причина: на iPhone запуск записи (разрешение микрофона, AudioWorklet) идёт дольше HOLD_MS. Отпускание пальца (или
pointercancel от окна разрешения) засчитывалось как «держали — отпустили» и звало остановку до того, как захват звука
готов: остановка падала, флаг ``ending`` оставался — «Стоп» и «Отправить» дальше молчали, поток распознавания висел.
Здесь: эмуляция iPhone (касания), getUserMedia отвечает через 0,8 с; касание и отпускание через 0,45 с; дальше —
«Стоп и отправить» (и Enter) работают: одно сообщение, строки записи нет, финал не дольше ~1,5 с. Плюс: финал от
службы не пришёл — уходит распознанное потоком (не ждём 90 с).
"""

import sys
import time

import _onebrowser  # noqa: F401  — e2e с браузером по одному на сервер (tests/heavy_lock.py)

PHRASE = "Покажи, что изменилось за сегодня"
SLOW_MIC = """() => { const g = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = (c) => new Promise((ok, no) => setTimeout(() => g(c).then(ok, no), 800)); }"""
SPY = """() => { window.__sent = []; const a = window.api;
  window.api = (p, b, ...r) => { if (p === '/api/send') window.__sent.push(b?.text); return a(p, b, ...r); }; }"""


def run(base: str):
    from playwright.sync_api import sync_playwright

    sep = "&" if "?" in base else "?"
    errs: list[str] = []
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        dev = {**p.devices["iPhone 13"]}
        dev.pop("default_browser_type", None)
        for q, how in (("", "ok"), ("&asr=slow", "enter")):
            ctx = br.new_context(**dev, permissions=["microphone"])
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"{base}{sep}open=@1&noscroll{q}")
            pg.wait_for_selector("#content .msg")
            pg.evaluate(SLOW_MIC)
            pg.evaluate(SPY)
            b = pg.locator("#mic").bounding_box()
            x, y = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
            pg.dispatch_event("#mic", "pointerdown", {"pointerType": "touch", "isPrimary": True, "button": 0,
                                                       "clientX": x, "clientY": y})
            pg.wait_for_timeout(450)                          # палец отпустили, пока запись ещё запускается
            pg.evaluate("document.dispatchEvent(new PointerEvent('pointerup', {pointerType: 'touch'}))")
            pg.wait_for_selector(".recbar.live .ok", timeout=5000)
            pg.wait_for_function("document.getElementById('input').value.split(' ').length >= 3", timeout=6000)
            t0 = time.perf_counter()
            if how == "ok":
                pg.locator(".recbar.live .ok").tap()           # «Стоп и отправить»
            else:
                pg.evaluate("sendText()")                     # Enter / «Отправить»
            pg.wait_for_function("window.__sent.length === 1 && !document.querySelector('.recbar') && !vs",
                                 timeout=4000)
            ms = (time.perf_counter() - t0) * 1000
            sent = pg.evaluate("window.__sent")
            assert sent and sent[0].startswith("Покажи"), f"{q}: ушло {sent}"
            assert ms < 2500, f"{q}: финал {ms:.0f} мс"
            print(f"{q or 'служба'}: отправлено за {ms:.0f} мс: {sent[0]}")
            ctx.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: запись на iPhone останавливается и отправляется всегда")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo&dev")
