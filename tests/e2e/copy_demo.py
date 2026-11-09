"""«Копировать» у каждого сообщения и у каждого блока кода (Playwright; pytest запускает, только если есть браузер).

    python tests/e2e/copy_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Буфер обмена перехвачен (navigator.clipboard.writeText → window.__clip). Проверки (390 и 1366, светлая и тёмная):
  (а) ответ Claude — «Копировать» внизу справа, после времени; копируется исходный markdown;
  (б) ваше сообщение — значок внизу справа (на ПК виден при наведении); вставленный вывод терминала — целиком;
  (в) короткий блок кода — кнопка справа сверху, копируется чистый текст; «Скопировано» на 1,5 с и обратно;
  (г) длинный свёрнутый блок — кнопка в заголовке: копирует все строки и блок не раскрывает;
  (д) после перерисовки (morph) кнопки у новых сообщений есть, у старых блоков — ровно одна, без двойной обёртки;
  (е) нет navigator.clipboard (WebView Telegram) — запасной путь execCommand("copy") с тем же текстом;
  (ж) простой режим — у сообщений и блоков кода то же. Консоль без ошибок.
"""

import sys

CLIP = """() => { window.__clip = null;
  const w = (t) => { window.__clip = t; return Promise.resolve(); };
  try { Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: w } }); }
  catch (e) { navigator.clipboard.writeText = w; } }"""
NOCLIP = """() => { window.__clip = null;
  const no = () => Promise.reject(new Error('нет'));
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: no } });
  document.execCommand = (c) => {
    window.__clip = c === 'copy' ? document.activeElement.value : null; return true; }; }"""


def clip(pg):
    return pg.evaluate("() => window.__clip")


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for dev, theme in (("phone", "light"), ("pc", "dark"), ("phone", "dark"), ("pc", "light")):
            tag = f"{dev} {theme}"
            kw = {"viewport": {"width": 1366, "height": 860}} if dev == "pc" else \
                {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
            ctx = br.new_context(**kw)
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"{base}{sep}open=@1&theme={theme}&noscroll")
            pg.wait_for_selector("#content .msg.ai[data-i='10'] .codebox .ccopy", timeout=10000)
            pg.evaluate(CLIP)

            # (а) ответ Claude: кнопка — последняя в строке действий, после времени; текст — исходный markdown
            ai = pg.locator("#content .msg.ai[data-i='8']")
            order = ai.locator(".acts > *").evaluate_all("els => els.map((e) => e.className || e.tagName)")
            assert order[-2:] == ["when", "BUTTON"], f"{tag}: порядок в строке ответа {order}"
            ai.locator(".acts [data-mcopy]").click()
            assert clip(pg) == pg.evaluate("() => hist.find((m) => m.i === 8).text"), f"{tag}: ответ скопирован не тот"
            assert "Скопировано" in ai.locator(".acts [data-mcopy]").inner_text(), f"{tag}: нет «Скопировано» у ответа"

            # (б) ваше сообщение: значок справа внизу; на ПК — по наведению
            me = pg.locator("#content .msg.me[data-i='7']")
            btn = me.locator(".macts .mcopy")
            if dev == "pc":
                pg.mouse.move(2, 2)
                assert btn.evaluate("b => getComputedStyle(b).opacity") == "0", f"{tag}: значок виден без наведения"
                me.hover()
                pg.wait_for_timeout(250)
                assert btn.evaluate("b => getComputedStyle(b).opacity") == "1", f"{tag}: значок не виден при наведении"
            bb, mb = btn.bounding_box(), me.bounding_box()
            assert bb["x"] + bb["width"] > mb["x"] + mb["width"] - 4, f"{tag}: значок не справа"
            btn.click()
            assert clip(pg) == "Сделай панель удобнее: тёмная тема и кнопки диалога", f"{tag}: {clip(pg)!r}"
            pg.locator("#content .msg.me[data-i='9'] .mcopy").click()
            got = clip(pg)
            ok = got.startswith("Проверь сборку") and "Last login" in got and got.endswith("0.01")
            assert ok, f"{tag}: терминал {got!r}"

            # (в) короткий блок кода
            cb = pg.locator("#content .msg.ai[data-i='10'] .codebox").first
            cbtn = cb.locator(".ccopy")
            pb, kb = cb.bounding_box(), cbtn.bounding_box()
            gap_top, gap_right = kb["y"] - pb["y"], pb["x"] + pb["width"] - (kb["x"] + kb["width"])
            assert gap_top < 12 and gap_right < 12, f"{tag}: кнопка не справа сверху"
            if shots and dev == "pc":
                cb.hover()
            cbtn.click()
            assert clip(pg) == "npm test", f"{tag}: блок {clip(pg)!r}"
            assert "Скопировано" in cbtn.inner_text(), f"{tag}: нет «Скопировано» у блока"
            if shots:
                pg.locator("#content .msg.ai[data-i='10']").screenshot(path=f"{shots}/copy-code-{dev}-{theme}.png")
            pg.wait_for_timeout(1700)
            assert "Скопировано" not in cbtn.inner_text() and cbtn.locator("svg").count() == 1, f"{tag}: не вернулась"

            # (г) длинный свёрнутый блок: копирует всё, не раскрывается
            lg = pg.locator("#content .msg.ai[data-i='10'] details.log")
            lg.locator("summary .ccopy").click()
            got = clip(pg)
            ok = got.startswith("PASS  tests/rooms/case-01") and len(got.split("\n")) == 24
            assert ok, f"{tag}: длинный {got[:60]!r}"
            assert lg.evaluate("d => d.open") is False, f"{tag}: блок раскрылся от «Копировать»"

            # (д) перерисовка: новое сообщение получает кнопки, старые блоки не оборачиваются дважды
            pg.evaluate("""() => { hist.push({ i: 50, role: 'user', text: 'новое', ts: '2026-10-29 09:30' },
                { i: 51, role: 'assistant', text: 'Готово:\\n\\n```\\necho привет\\n```', ts: '2026-10-29 09:31' });
                renderChat(false); renderChat(false); }""")
            pg.wait_for_selector("#content .msg.ai[data-i='51'] .codebox .ccopy")
            assert pg.locator("#content .msg.ai[data-i='10'] .codebox").count() == 1, f"{tag}: двойная обёртка"
            assert pg.locator("#content .msg.me[data-i='50'] .mcopy").count() == 1
            pg.locator("#content .msg.ai[data-i='51'] .ccopy").click()
            assert clip(pg) == "echo привет", f"{tag}: новый блок {clip(pg)!r}"
            n_msg = pg.locator("#content .msg[data-i]").count()
            assert pg.locator("#content .msg[data-i] [data-mcopy]").count() == n_msg, f"{tag}: не у всех сообщений"
            if shots:
                pg.screenshot(path=f"{shots}/copy-chat-{dev}-{theme}.png", full_page=False)

            # (е) WebView без clipboard — execCommand
            pg.evaluate(NOCLIP)
            pg.locator("#content .msg.ai[data-i='51'] .ccopy").click()
            assert clip(pg) == "echo привет", f"{tag}: execCommand {clip(pg)!r}"
            assert pg.locator(".sheet-bg").count() == 0, f"{tag}: шторка «вручную» при рабочем execCommand"
            ctx.close()

            # (ж) простой режим
            ctx = br.new_context(**kw)
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"{base}{sep}simple=1&theme={theme}&noscroll")
            pg.wait_for_selector("#sFeed .msg[data-i] .mcopy", timeout=10000)
            pg.evaluate(CLIP)
            n_msg = pg.locator("#sFeed .msg[data-i]").count()
            assert pg.locator("#sFeed .msg[data-i] .mcopy").count() == n_msg, f"{tag}: простой — не у всех"
            first = pg.locator("#sFeed .msg[data-i]").first
            first.hover()
            first.locator(".mcopy").click()
            assert clip(pg) == pg.evaluate("() => SIM.hist[0].text"), f"{tag}: простой — {clip(pg)!r}"
            pg.evaluate("""() => {
                SIM.hist.push({ i: 90, role: 'assistant', text: 'Команда:\\n\\n```\\nls -la\\n```', ts: '' });
                sRender(false); }""")
            pg.wait_for_selector("#sFeed .msg[data-i='90'] .codebox .ccopy")
            pg.locator("#sFeed .msg[data-i='90'] .ccopy").click()
            assert clip(pg) == "ls -la", f"{tag}: простой блок {clip(pg)!r}"
            if shots:
                pg.screenshot(path=f"{shots}/copy-simple-{dev}-{theme}.png")
            ctx.close()
            print(f"{tag}: ок")
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: «Копировать» у сообщений и блоков кода")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo", sys.argv[2] if len(sys.argv) > 2 else "")
