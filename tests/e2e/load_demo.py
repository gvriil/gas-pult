"""Загрузка без лишнего (план UX, пункт 10; Playwright; pytest запускает, только если есть браузер).

    python tests/e2e/load_demo.py http://127.0.0.1:8797/?demo

marked и DOMPurify грузятся после первого показа (не в <head>): запрос к ним начинается позже первой отрисовки,
ответы после загрузки — с разметкой (жирный, код), до неё — простой текст. Словарь кэшируется: второй заход берёт его
из localStorage. 390 и 1366, светлая и тёмная; консоль без ошибок.
"""

import sys


def run(base: str):
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
                src = pg.evaluate("() => fetch(location.href).then((r) => r.text())")
                assert "marked.min.js\"></script>" not in src, f"{tag}: marked снова в <head>"
                pg.wait_for_function("() => !!(window.marked && window.DOMPurify)", timeout=8000)
                pg.wait_for_selector("#content .msg.ai .md strong", timeout=4000)
                t = pg.evaluate("""() => {
                  const fcp = performance.getEntriesByName('first-contentful-paint')[0]?.startTime || 0;
                  const lib = performance.getEntriesByType('resource').find((e) => e.name.includes('marked'));
                  return [fcp, lib ? lib.startTime : -1];
                }""")
                assert t[1] >= t[0] > 0, f"{tag}: marked начал грузиться до первой отрисовки ({t})"
                assert pg.evaluate("() => !!localStorage.getItem('dict:ru')"), f"{tag}: словарь не закэширован"
                pg.reload()
                assert pg.evaluate("() => Object.keys(DICT).length > 50"), f"{tag}: второй заход — словарь не из кэша"
                ctx.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: загрузка без лишнего")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo")
