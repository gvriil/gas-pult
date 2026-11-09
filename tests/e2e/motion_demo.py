"""Переходы экранов на телефоне (план UX, пункт 7; Playwright; pytest запускает, только если есть браузер).

    python tests/e2e/motion_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

390 px, касания (CDP Input.dispatchTouchEvent):
  (а) карточка на главной → сессия въезжает справа (анимация slidein 0,2 с, только transform);
  (б) свайп от левого края в сессии: экран идёт за пальцем (translateX ≈ сдвигу), под ним видна главная;
      отпустили дальше трети — открыта главная;
  (в) короткий свайп (меньше трети, медленно) — сессия возвращается на место;
  (г) свайп от края в сессии НЕ открывает панель чатов; на главной тот же свайп её открывает (#149 не сломан);
  (д) prefers-reduced-motion — без анимации въезда.
Светлая и тёмная; на 1366 переходов нет (две колонки). Консоль без ошибок.
"""

import sys


def touch(cdp, kind, x, y):
    pts = [] if kind == "touchEnd" else [{"x": x, "y": y, "id": 1}]
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": pts})


def drag(pg, cdp, xs, y=420, pause=16):
    touch(cdp, "touchStart", xs[0], y)
    for x in xs[1:]:
        touch(cdp, "touchMove", x, y)
        pg.wait_for_timeout(pause)


def tx(pg, sel):
    return pg.evaluate(f"() => new DOMMatrix(getComputedStyle(document.querySelector('{sel}')).transform).m41")


def open_card(pg):
    pg.locator("#sessionsView .card[data-id]").first.click()
    pg.wait_for_function("() => view === 'session'")


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for th in ("light", "dark"):
            tag = f"390 {th}"
            ctx = br.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            cdp = ctx.new_cdp_session(pg)
            pg.goto(f"{base}{sep}home&theme={th}&noscroll")
            pg.wait_for_selector("#sessionsView .card[data-id]")

            # (а) въезд справа
            open_card(pg)
            a = pg.evaluate("() => { const cs = getComputedStyle(document.getElementById('session'));"
                            " return [cs.animationName, cs.animationDuration]; }")
            assert a == ["slidein", "0.2s"], f"{tag}: сессия не въезжает справа: {a}"
            pg.wait_for_timeout(350)
            gone = pg.evaluate("() => !document.getElementById('session').classList.contains('slide-in')")
            assert gone, f"{tag}: класс въезда не снят"

            # (в) короткий медленный свайп — возврат
            drag(pg, cdp, [6, 20, 40, 60, 80], pause=60)
            assert abs(tx(pg, "#session") - 74) < 12, f"{tag}: экран не идёт за пальцем ({tx(pg, '#session')})"
            touch(cdp, "touchEnd", 0, 0)
            pg.wait_for_timeout(350)
            assert pg.evaluate("() => view") == "session", f"{tag}: короткий свайп ушёл с сессии"
            assert tx(pg, "#session") == 0, f"{tag}: сессия не вернулась на место"
            assert not pg.evaluate("() => NAV.open"), f"{tag}: свайп в сессии открыл панель чатов"

            # (б) длинный свайп — назад, под пальцем видна главная
            drag(pg, cdp, [6, 40, 90, 140, 190, 240])
            under = pg.evaluate("() => getComputedStyle(document.getElementById('home')).display")
            assert under == "block", f"{tag}: под сессией не видна главная ({under})"
            if shots:
                pg.screenshot(path=f"{shots}/motion-drag-{th}.png")
            touch(cdp, "touchEnd", 0, 0)
            pg.wait_for_function("() => view === 'home'", timeout=2000)
            pg.wait_for_timeout(100)
            assert not pg.evaluate("() => document.body.classList.contains('back-drag')"), f"{tag}: back-drag не снят"
            assert tx(pg, "#session") == 0 and tx(pg, ".dock") == 0, f"{tag}: transform остался"
            assert not pg.evaluate("() => NAV.open"), f"{tag}: свайп «назад» открыл панель чатов"

            # (г) на главной свайп от края — панель чатов (#149)
            drag(pg, cdp, [6, 60, 140, 220, 280])
            touch(cdp, "touchEnd", 0, 0)
            pg.wait_for_timeout(400)
            assert pg.evaluate("() => NAV.open"), f"{tag}: на главной свайп от края не открыл панель чатов"
            ctx.close()

        # (д) prefers-reduced-motion
        ctx = br.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True,
                             reduced_motion="reduce")
        pg = ctx.new_page()
        pg.goto(f"{base}{sep}home&noscroll")
        pg.wait_for_selector("#sessionsView .card[data-id]")
        open_card(pg)
        a = pg.evaluate("() => getComputedStyle(document.getElementById('session')).animationName")
        assert a == "none", f"reduced-motion: въезд с анимацией ({a})"
        ctx.close()

        # 1366: две колонки — без въезда
        ctx = br.new_context(viewport={"width": 1366, "height": 900})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{base}{sep}home&noscroll")
        pg.wait_for_selector("#sessionsView .card[data-id]")
        open_card(pg)
        a = pg.evaluate("() => getComputedStyle(document.getElementById('session')).animationName")
        assert a == "none", f"1366: въезд на компьютере ({a})"
        ctx.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: переходы экранов и свайп «назад»")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo", sys.argv[2] if len(sys.argv) > 2 else "")
