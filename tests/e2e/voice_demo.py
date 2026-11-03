"""Перемотка озвучки (задача 29; Playwright — pytest запускает, только если есть браузер).

    python tests/e2e/voice_demo.py http://127.0.0.1:8797/?demo [папка-для-скриншотов]

Телефон 390×844, полный режим, сессия открыта (``?demo&open=@1``), «Кратко» у последнего ответа (в демо — 40 с тона).
Кнопки «−15 с», пауза, «+15 с» и ✕ — не меньше 44×44; время «0:10 / 0:40»; −15 на 0:10 даёт 0:00; +15 у конца — конец;
полоса тянется пальцем; Media Session: seekbackward/seekforward/seekto есть, previoustrack/nexttrack не заданы;
место переживает перезагрузку панели (▶ продолжает оттуда же); мини-плеер не перекрывает поле ввода. Консоль чистая.
"""

import sys

# Запоминаем, какие действия Media Session панель назначила, — чтобы нажать «наушниками».
SPY = """(() => {
  window.__ms = {};
  if (!("mediaSession" in navigator)) return;
  const orig = navigator.mediaSession.setActionHandler.bind(navigator.mediaSession);
  navigator.mediaSession.setActionHandler = (a, f) => { window.__ms[a] = f; try { orig(a, f); } catch (e) {} };
})();"""


def cross(a, b) -> bool:
    return a["x"] < b["x"] + b["width"] - 0.5 and b["x"] < a["x"] + a["width"] - 0.5 and \
        a["y"] < b["y"] + b["height"] - 0.5 and b["y"] < a["y"] + a["height"] - 0.5


def at(pg, t: float):
    pg.evaluate(f"player().currentTime = {t}; voiceTick()")


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True, args=["--autoplay-policy=no-user-gesture-required"])
        for theme in ("light", "dark"):
            pg = br.new_page(viewport={"width": 390, "height": 844})
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.add_init_script(SPY)
            pg.goto(f"{base}{sep}open=@1&theme={theme}")
            pg.evaluate("localStorage.removeItem('voicePos')")
            pg.locator("[data-say]").last.click()
            pg.wait_for_selector("[data-voice].play", timeout=8000)
            pg.wait_for_function("player().duration > 30", timeout=8000)
            dur = pg.evaluate("player().duration")

            # Крупные кнопки рядом с паузой.
            for sel in ('[data-voice] [data-vseek="-15"]', "[data-voice] [data-vtoggle]",
                        '[data-voice] [data-vseek="15"]', "[data-voice] [data-vstop]"):
                b = pg.locator(sel).bounding_box()
                assert b and b["width"] >= 44 and b["height"] >= 44, f"{sel}: {b} меньше 44 px"
            assert pg.locator("[data-voice] .bar").bounding_box()["height"] >= 44, "полосу трудно попасть пальцем"

            pg.click("[data-voice] [data-vtoggle]")                  # пауза: дальше время стоит на месте
            pg.wait_for_selector("[data-voice].pause")
            at(pg, 10)
            assert pg.text_content("[data-voice] .t") == "0:10 / 0:40", pg.text_content("[data-voice] .t")
            pg.click('[data-voice] [data-vseek="-15"]')
            assert pg.evaluate("player().currentTime") == 0, "−15 на 0:10 — не 0:00"
            assert pg.text_content("[data-voice] .t") == "0:00 / 0:40"
            at(pg, dur - 3)
            pg.click('[data-voice] [data-vseek="15"]')
            assert abs(pg.evaluate("player().currentTime") - dur) < 0.05, "+15 у конца — не конец"
            at(pg, 5)
            pg.click('[data-voice] [data-vseek="15"]')
            assert abs(pg.evaluate("player().currentTime") - 20) < 0.05

            # Полоса: тянем пальцем (мышью) до середины — там и окажемся.
            bar = pg.locator("[data-voice] .bar").bounding_box()
            y = bar["y"] + bar["height"] / 2
            pg.mouse.move(bar["x"] + 4, y)
            pg.mouse.down()
            pg.mouse.move(bar["x"] + bar["width"] * 0.3, y, steps=4)
            pg.mouse.move(bar["x"] + bar["width"] / 2, y, steps=4)
            assert pg.text_content("[data-voice] .t") == "0:20 / 0:40", "время не следует за пальцем"
            pg.mouse.up()
            assert abs(pg.evaluate("player().currentTime") - dur / 2) < 1, "полоса не перемотала"

            # Наушники и экран блокировки — те же ±15 с; переключение треков не трогаем.
            acts = pg.evaluate("Object.keys(window.__ms)")
            assert {"play", "pause", "seekbackward", "seekforward", "seekto"} <= set(acts), acts
            assert "previoustrack" not in acts and "nexttrack" not in acts, acts
            at(pg, 30)
            pg.evaluate("__ms.seekbackward({ action: 'seekbackward' })")
            assert abs(pg.evaluate("player().currentTime") - 15) < 0.05
            pg.evaluate("__ms.seekforward({ action: 'seekforward', seekOffset: 15 })")
            assert abs(pg.evaluate("player().currentTime") - 30) < 0.05
            pg.evaluate("__ms.seekto({ action: 'seekto', seekTime: 12 })")
            assert abs(pg.evaluate("player().currentTime") - 12) < 0.05

            # Мини-плеер (перешли в другую сессию) — над нижней панелью, поле ввода не закрывает.
            pg.evaluate("openSession('@2')")
            pg.wait_for_selector("#mini:not([hidden])", timeout=8000)
            pg.wait_for_timeout(400)
            mini = pg.locator("#mini").bounding_box()
            for g in ("#input", "#composer", "#dock"):
                assert not cross(mini, pg.locator(g).bounding_box()), f"мини-плеер перекрывает {g}"
            for sel in ('#mini [data-vseek="-15"]', "#mini [data-vtoggle]", '#mini [data-vseek="15"]'):
                b = pg.locator(sel).bounding_box()
                assert b["width"] >= 44 and b["height"] >= 44, sel
            if shots:
                pg.screenshot(path=f"{shots}/voice-mini-{theme}.png")
            pg.evaluate("openSession('@1')")
            pg.wait_for_selector("[data-voice]", timeout=8000)
            if shots:
                pg.locator("[data-voice]").scroll_into_view_if_needed()
                pg.screenshot(path=f"{shots}/voice-{theme}.png")

            # Свернули панель / она перезагрузилась — продолжаем с того же места.
            at(pg, 21)
            pg.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            pg.evaluate("voicePos(true)")
            pg.reload()
            v = "[data-voice], #mini:not([hidden])"                     # в сообщении или мини-плеером
            pg.wait_for_selector("[data-voice].pause, #mini:not([hidden]).pause", timeout=8000)
            assert pg.locator(v).first.locator(".t").text_content() == "0:21", pg.locator(v).first.inner_text()
            pg.locator(v).first.locator("[data-vtoggle]").click()
            pg.wait_for_selector("#mini.play, [data-voice].play", timeout=8000)
            t = pg.evaluate("player().currentTime")
            assert 20.5 <= t < 24, f"после перезагрузки начали с {t}, а не с 0:21"
            # ✕ — место забыто.
            pg.locator(v).first.locator("[data-vstop]").click()
            assert pg.evaluate("localStorage.getItem('voicePos')") is None
            pg.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs[:5]}"


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    print("ok")
