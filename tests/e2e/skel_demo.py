"""Скелетоны вместо «Загружаю…» (план UX, пункт 3; Playwright; pytest запускает, только если есть браузер).

    python tests/e2e/skel_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Демо с медленной сетью при загрузке (``&slow=1200``): пока данных нет, на главной — серые карточки, в сессии и в
простом режиме — заглушки сообщений; потом данные встают на их место. Сдвиг раскладки (CLS) после первой отрисовки
скелетонов — меньше 0,05. 390 и 1366, светлая и тёмная; консоль без ошибок.
"""

import sys

CLS = """() => { window.__cls = 0;
  new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; })
  .observe({ type: 'layout-shift', buffered: false }); }"""


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for w in (390, 1366):
            for th in ("light", "dark"):
                tag = f"{w} {th}"
                for q, skel, real in (("home", "#sessionsView .card.skel", "#sessionsView .card[data-id]"),
                                      ("open=@1", "#content .msg.skel", "#content .msg[data-i]"),
                                      ("simple=1", "#sFeed .msg.skel", "#sFeed .msg[data-i]")):
                    ctx = br.new_context(viewport={"width": w, "height": 860})
                    pg = ctx.new_page()
                    pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                    pg.on("pageerror", lambda e: errs.append(str(e)))
                    pg.goto(f"{base}{sep}{q}&theme={th}&slow=1200&noscroll")
                    pg.wait_for_selector(skel, state="visible", timeout=10000)
                    if shots:
                        pg.screenshot(path=f"{shots}/skel-{q.split('=')[0]}-{w}-{th}.png")
                    pg.evaluate(CLS)
                    pg.wait_for_selector(real, state="visible", timeout=8000)
                    pg.wait_for_timeout(500)
                    assert pg.locator(".skel").filter(visible=True).count() == 0, f"{tag} {q}: скелетоны остались"
                    cls = pg.evaluate("() => window.__cls")
                    print(f"{tag} {q}: CLS {cls:.3f}")
                    assert cls < 0.05, f"{tag} {q}: сдвиг раскладки {cls:.3f}"
                    ctx.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: скелетоны вместо «Загружаю…»")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo", sys.argv[2] if len(sys.argv) > 2 else "")
