"""Стартовый экран и одно число расхода в демо (Playwright), 22.11.

    python tests/e2e/spend_start_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Старт в чистом профиле: 390 — сразу последний/активный чат («Чат прежде всего», CHANGELOG 01.11, PR #28; `?home` —
список), полоска демо в разметке есть; 390 `?home` и 1366 — главная, полоска демо на экране; `?open=@2` — этот чат.
Расход: меню (#navSpend), чип «Сегодня» на главной, лист «Расход» и экран «Расход по ценам API» — одна сумма за
сегодня с подписью «оценка» (источник один — d.cost.today; /api/spend отдаёт его в live). Светлая и тёмная тема,
консоль без ошибок.
"""

import re
import sys

import _onebrowser  # noqa: F401  — e2e с браузером по одному на сервер (tests/heavy_lock.py)

USD = re.compile(r"\$\d[\d,]*(?:\.\d\d)?")
READY = ("typeof meta !== 'undefined' && meta && typeof view !== 'undefined' && typeof sessions !== 'undefined'"
         " && sessions.length")
BAR = """() => { const e = document.getElementById('demoBar'), r = e.getBoundingClientRect();
  return { on: !e.hidden && getComputedStyle(e).display !== 'none',
           seen: r.height > 0 && r.top >= 0 && r.bottom <= innerHeight }; }"""


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    phone = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
    desk = {"viewport": {"width": 1366, "height": 860}}
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)

        def page(kw, q):
            ctx = br.new_context(**kw)                       # чистый профиль: без localStorage и куки
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"{base}{sep}{q}" if q else base)
            pg.wait_for_function(READY, timeout=10000)
            pg.wait_for_timeout(1500)                        # стартовый выбор экрана — после первого опроса
            return ctx, pg

        # 1. стартовый экран
        ctx, pg = page(phone, "")
        st = pg.evaluate("({ view, current })")
        assert st["view"] == "session" and st["current"], f"390: ожидался последний чат, а не {st}"
        assert pg.evaluate(BAR)["on"], "390: полоски демо нет в разметке"
        pg.evaluate("document.getElementById('scroller').scrollTop = 99999")   # полоска закреплена (штаб 22.11)
        pg.mouse.wheel(0, 3000)
        pg.wait_for_timeout(600)
        bar = pg.evaluate(BAR)
        assert bar["seen"], f"390: после прокрутки чата полоска демо уехала: {bar}"
        ctx.close()
        for kw, q, tag in ((phone, "home", "390 ?home"), (desk, "", "1366")):
            ctx, pg = page(kw, q)
            assert pg.evaluate("view") == "home", f"{tag}: ожидалась главная, а не {pg.evaluate('view')}"
            bar = pg.evaluate(BAR)
            assert bar["on"] and bar["seen"], f"{tag}: полоски демо не видно: {bar}"
            ctx.close()
        ctx, pg = page(phone, "open=@2")
        assert pg.evaluate("({ view, current })") == {"view": "session", "current": "@2"}, "?open=@2 не открыл чат"
        ctx.close()

        # 2. расход: одно число и одна подпись
        for theme in ("light", "dark"):
            for kw, w in ((desk, 1366), (phone, 390)):
                tag = f"{w}/{theme}"
                ctx, pg = page(kw, f"home&theme={theme}&noscroll")
                pg.evaluate("try { localStorage.setItem('gp:tourDone', '1'); } catch (e) {}")
                nav = pg.text_content("#navSpend") or ""
                chip = pg.text_content("[data-cost-sum]") or ""
                n1, n2 = USD.findall(nav), USD.findall(chip)
                assert n1 and n2 and n1[0] == n2[0], f"{tag}: меню «{nav}» и главная «{chip}» — разные суммы"
                assert nav.startswith("Сегодня") and "оценка" in nav and "оценка" in chip, \
                    f"{tag}: нет подписи «Сегодня … · оценка»: «{nav}» / «{chip}»"
                if shots:
                    pg.screenshot(path=f"{shots}/glavnaya-{w}-{theme}.png")
                pg.evaluate("spendOpen()")                   # экран «Расход по ценам API» (из меню)
                pg.wait_for_selector("[data-spend-sum]", timeout=5000)
                big = pg.text_content("[data-spend-sum]") or ""
                assert USD.findall(big)[:1] == n1[:1], f"{tag}: экран расхода «{big}», меню «{n1[0]}»"
                if shots:
                    pg.screenshot(path=f"{shots}/rashod-{w}-{theme}.png")
                pg.click(".spend [data-close]")
                pg.click("[data-cost-sum]")                  # лист «Расход» с главной
                pg.wait_for_selector(".sheet", timeout=3000)
                sh = pg.text_content(".sheet") or ""
                assert n1[0] in sh and "оценка" in sh, f"{tag}: лист «Расход» без той же суммы: {sh[:120]}"
                ctx.close()
        br.close()
    assert not errs, errs
    print("spend_start_demo ok")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
