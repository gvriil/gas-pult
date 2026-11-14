"""Enter во время записи голоса (#208; Playwright — pytest запускает, только если есть браузер).

    python tests/e2e/voice_enter_demo.py http://127.0.0.1:8797/?demo

Жалоба владельца 14.11: «Enter нажимаю — в чат приходит сообщение, а запись не заканчивается». Ожидается: Enter во
время диктовки = «Стоп и отправить»: запись останавливается, приходит итог распознавания, уходит ОДНО сообщение с
полным текстом, строки записи нет, микрофон выключен. Демо: распознавание подменено (DemoStt), микрофон — поддельный.
Полный режим (поле «Сообщение») и простой режим; телефон 390 и компьютер 1366.
"""

import sys

PHRASE = "Покажи, что изменилось за сегодня"
SPY = """() => { window.__sent = []; const a = window.api;
  window.api = (p, b, ...r) => { if (p === '/api/send') window.__sent.push(b?.text); return a(p, b, ...r); }; }"""


def run(base: str):
    from playwright.sync_api import sync_playwright

    sep = "&" if "?" in base else "?"
    errs: list[str] = []
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        for w, h in ((390, 844), (1366, 860)):
            ctx = br.new_context(viewport={"width": w, "height": h}, permissions=["microphone"])
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"{base}{sep}open=@1&noscroll")
            pg.wait_for_selector("#content .msg")
            pg.evaluate(SPY)
            pg.click("#mic")                                  # касание — диктовка до «Стоп»
            pg.wait_for_function("document.getElementById('input').value.split(' ').length >= 3", timeout=6000)
            pg.focus("#input")
            pg.keyboard.press("Enter")                        # Enter во время записи
            pg.wait_for_function("window.__sent.length === 1 && !document.querySelector('.recbar') && !vs",
                                 timeout=6000)
            pg.wait_for_timeout(1500)                         # второго сообщения и записи дальше — нет
            sent = pg.evaluate("window.__sent")
            assert sent == [PHRASE], f"{w}: ушло {sent}"
            assert pg.evaluate("!vs && !rec && !document.querySelector('.recbar')"), f"{w}: запись не остановлена"
            assert pg.evaluate("!micStream || micStream.getAudioTracks().every((t) => !t.enabled)"), \
                f"{w}: микрофон не выключен"
            # Enter, пока текста ещё нет (сразу после начала): всё равно одно сообщение с итогом, без пустого
            pg.evaluate("() => micTap(MIC_FULL)")            # то же, что касание микрофона
            pg.wait_for_function("!!vs", timeout=3000)
            pg.focus("#input")
            pg.keyboard.press("Enter")
            pg.wait_for_function("!vs && !document.querySelector('.recbar')", timeout=6000)
            pg.wait_for_timeout(800)
            assert len(pg.evaluate("window.__sent")) <= 2 and "" not in pg.evaluate("window.__sent"), \
                f"{w}: {pg.evaluate('window.__sent')}"
            ctx.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: Enter во время записи — стоп, итог, одно сообщение, микрофон выключен")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo")
