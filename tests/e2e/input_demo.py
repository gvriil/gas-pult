"""Поле ввода без лишней раскладки (план UX, пункт 8; Playwright; pytest запускает, только если есть браузер).

    python tests/e2e/input_demo.py http://127.0.0.1:8797/?demo

- Поле растёт со строками: измерение — один раз за кадр, сколько бы событий ввода ни пришло; до 6 строк, дальше —
  прокрутка внутри.
- Кнопка «к последнему» поднимается над полем через transform (без style.bottom).
- Строка статуса и кнопки эскалации («Проверить статус» …) не уходят под поле ввода и на 390, и с длинным текстом.
390 и 1366, светлая и тёмная; консоль без ошибок.
"""

import sys

SPY = """() => {                                   // сколько раз поле мерили (getComputedStyle на #input)
  window.__fits = 0;
  const orig = window.getComputedStyle;
  window.getComputedStyle = function (el, ...a) {
    if (el && el.id === "input") window.__fits++;
    return orig.call(this, el, ...a);
  };
}"""

TYPE25 = "() => { const t = $('input'); for (let i = 0; i < 25; i++) { t.value += 'слово '; grow(); } }"


def run(base: str):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for w, h in ((390, 844), (1366, 900)):
            for th in ("light", "dark"):
                tag = f"{w} {th}"
                pg = br.new_page(viewport={"width": w, "height": h})
                pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(f"{base}{sep}open=@1&theme={th}")
                pg.wait_for_selector("#content .msg")
                pg.wait_for_timeout(600)
                pg.evaluate(SPY)
                pg.evaluate(TYPE25)
                pg.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
                fits = pg.evaluate("() => __fits")
                assert fits == 1, f"{tag}: 25 событий ввода — {fits} измерений поля, ждали одно за кадр"

                pg.evaluate("() => { $('input').value = Array(12).fill('строка').join('\\n'); grow(); }")
                pg.wait_for_timeout(250)
                r = pg.evaluate("""() => { const t = $('input'), cs = getComputedStyle(t);
                  return [t.offsetHeight, parseFloat(cs.lineHeight), t.style.overflowY]; }""")
                assert r[0] <= r[1] * 6 + 40 and r[2] == "auto", f"{tag}: поле больше 6 строк или без прокрутки: {r}"

                pg.evaluate("() => { actProg.at = Date.now() - 70000; paintEsc(); }")       # все три кнопки эскалации
                pg.evaluate("() => { SC.scrollTop = SC.scrollHeight; }")
                pg.wait_for_timeout(400)
                g = pg.evaluate("""() => ({ dock: $('dock').getBoundingClientRect().top,
                  act: $('act').getBoundingClientRect().bottom,
                  actx: $('actx').hidden ? 0 : $('actx').getBoundingClientRect().bottom })""")
                assert g["act"] <= g["dock"] and g["actx"] <= g["dock"], f"{tag}: статус под полем ввода: {g}"

                # «прилипание к низу» (#147) — снять, иначе лента сама вернётся вниз
                pg.evaluate("() => { stick = 0; $('input').value = ''; grow(); }")
                pg.wait_for_timeout(300)
                pg.evaluate("() => { SC.scrollTop = 0; SC.dispatchEvent(new Event('scroll')); }")
                pg.wait_for_selector("#toBottom:not([hidden])", timeout=3000)
                pg.wait_for_timeout(300)
                tb = pg.evaluate("""() => { const b = $('toBottom'), d = $('dock');
                  return [b.style.bottom, getComputedStyle(b).transform, b.getBoundingClientRect().bottom,
                          d.classList.contains('hide') ? innerHeight : d.getBoundingClientRect().top]; }""")
                assert tb[0] == "" and tb[1].startswith("matrix"), f"{tag}: кнопка «к последнему» — не transform: {tb}"
                assert tb[2] <= tb[3] + 1, f"{tag}: кнопка «к последнему» под полем ввода: {tb}"
                pg.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: поле ввода")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo")
