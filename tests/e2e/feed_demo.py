"""Лента по центру и новые сообщения (план UX, пункт 6; Playwright; pytest запускает, только если есть браузер).

    python tests/e2e/feed_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

На компьютере (1366) лента — колонка ~760 px по центру основной области, поле ввода той же ширины и на той же линии.
Первая отрисовка ленты — без анимации; новое сообщение появляется (opacity + translateY 8 px, ~150 мс), прежние и
заменённые — нет; при prefers-reduced-motion анимации нет совсем. 390 и 1366, светлая и тёмная; консоль без ошибок.
"""

import sys

NEW_MSG = """() => {
  const i = Math.max(...hist.map((m) => m.i)) + 1;
  hist = [...hist, { role: "assistant", i, text: "Готово: **три** файла", ts: Date.now() / 1000 }];
  renderChat(false);
  const el = document.querySelector(`#content .msg[data-i='${i}']`), cs = getComputedStyle(el);
  return { name: cs.animationName, dur: cs.animationDuration,
           others: [...document.querySelectorAll('#content .msg')]
             .filter((x) => x !== el && x.getAnimations().length).length };
}"""
BOX = """() => { const r = (s) => { const b = document.querySelector(s).getBoundingClientRect();
    return [Math.round(b.left), Math.round(b.width)]; };
  const main = document.querySelector('main').getBoundingClientRect();
  return { msg: r('#content'), comp: r('#composer'), mainL: Math.round(main.left), mainW: Math.round(main.width) }; }"""


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for w in (390, 1366):
            for th in ("light", "dark"):
                tag = f"{w} {th}"
                ctx = br.new_context(viewport={"width": w, "height": 860})
                pg = ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(f"{base}{sep}open=@1&theme={th}&noscroll")
                pg.wait_for_selector("#content .msg[data-i]")
                pg.wait_for_timeout(600)
                first = pg.evaluate("() => document.querySelectorAll('#content .msg.enter').length")
                assert first == 0, f"{tag}: первая отрисовка ленты с анимацией ({first})"
                b = pg.evaluate(BOX)
                if w == 1366:
                    assert 740 <= b["msg"][1] <= 770, f"{tag}: лента не ~760 px: {b}"
                    assert b["msg"] == b["comp"], f"{tag}: поле ввода не той же ширины и линии, что лента: {b}"
                    centre = b["mainL"] + b["mainW"] / 2 - (b["msg"][0] + b["msg"][1] / 2)
                    assert abs(centre) <= 2, f"{tag}: лента не по центру ({centre})"
                else:
                    assert b["msg"][1] >= w - 40, f"{tag}: на телефоне лента сузилась: {b}"
                r = pg.evaluate(NEW_MSG)
                assert r["name"] == "msgin" and r["dur"] == "0.15s", f"{tag}: новое сообщение без анимации: {r}"
                assert r["others"] == 0, f"{tag}: прежние сообщения снова «появляются»: {r}"
                if shots:
                    pg.wait_for_timeout(300)
                    pg.screenshot(path=f"{shots}/feed-{w}-{th}.png")
                ctx.close()
        ctx = br.new_context(viewport={"width": 390, "height": 860}, reduced_motion="reduce")
        pg = ctx.new_page()
        pg.goto(f"{base}{sep}open=@1&noscroll")
        pg.wait_for_selector("#content .msg[data-i]")
        r = pg.evaluate(NEW_MSG)
        assert r["name"] == "none", f"prefers-reduced-motion: анимация осталась: {r}"
        ctx.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: лента по центру, новые сообщения появляются")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo", sys.argv[2] if len(sys.argv) > 2 else "")
