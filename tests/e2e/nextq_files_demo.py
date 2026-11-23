"""Отзывы тестировщика по фокус-чату 22.11 (Playwright; pytest запускает, только если есть браузер).

    python tests/e2e/nextq_files_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Демо ``&nq=file``: ваш снимок без подписи, документ с подписью и ответ с фразами «Можно спросить» и образцом текста.
Обычный чат (``open=@1``) и демо фокус-ссылки (``focus``); WebKit 390 (телефон) и Chromium 1366, светлая и тёмная.
  (а) фразы — кнопками под ответом, подпись «Можно спросить:», подсказка при первом показе; нажатие ставит фразу в
      поле и курсор в конец, НЕ отправляет (нет ожидающего сообщения и запроса /api/send); подсказка уходит;
  (б) у блока кода и у образца текста (цитата) — «Копировать» с подписью, видна без наведения; копирует чистый
      текст; после нажатия — «Скопировано»;
  (в) лента: «Снимок получен: <имя>» и «Файл получен: <имя>», подпись остаётся, «Посмотри файл.» и пути не видны.
Консоль без ошибок.
"""

import sys

import _onebrowser  # noqa: F401  — e2e с браузером по одному на сервер (tests/heavy_lock.py)

CLIP = """() => { window.__clip = null;
  const w = (t) => { window.__clip = t; return Promise.resolve(); };
  try { Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: w } }); }
  catch (e) { navigator.clipboard.writeText = w; } }"""
NOISE = ("404", "interactive-widget")
PHRASES = ["Сколько дублей нашлось по телефону?", "Покажи дубли списком",
           "Объедини дубли, но сначала покажи, что изменится"]
SAMPLE = "Здравствуйте! Мы объединили ваши записи — теперь все бонусы на одной карте."


def check(pg, tag: str, phone: bool, shots: str, name: str):
    box = pg.locator("#content .nextq")
    box.wait_for(timeout=15000)
    pg.wait_for_selector("#content .nextq .nq")
    assert box.locator(".nq-h").inner_text() == "Можно спросить:", f"{tag}: нет подписи группы"
    assert [x.inner_text() for x in box.locator(".nq").all()] == PHRASES, f"{tag}: фразы {box.inner_text()!r}"
    assert box.locator(".nq svg").count() == 3, f"{tag}: у фраз нет значка «вставить»"
    assert "встанет в поле" in box.locator(".nq-tip").inner_text(), f"{tag}: нет подсказки при первом показе"
    # (в) лента: файлы
    got = [x.inner_text() for x in pg.locator("#content .msg.me .fgot").all()]
    assert got == ["Снимок получен: таблица-клиентов.png", "Файл получен: клиенты-октябрь.xlsx"], f"{tag}: {got}"
    feed = pg.locator("#content").inner_text()
    assert "Посмотри файл." not in feed and "/home/u/" not in feed, f"{tag}: в ленте служебный текст или путь"
    assert "Сверь с прошлым месяцем" in feed, f"{tag}: подпись к файлу пропала"
    if shots:
        first = pg.locator("#content .msg.me .fgot").first
        first.evaluate("e => e.closest('.msg').scrollIntoView({ block: 'center' })")
        pg.wait_for_timeout(400)
        pg.screenshot(path=f"{shots}/{name}-0-файлы-и-образец.png")
        box.evaluate("e => e.scrollIntoView({ block: 'end' })")
        pg.wait_for_timeout(400)
        pg.screenshot(path=f"{shots}/{name}-1-фразы.png")
    # (б) «Копировать» у образца текста и блока кода: подпись видна без наведения
    last = pg.locator("#content .msg.ai").last
    qb = last.locator(".codebox blockquote")
    assert qb.count() == 1, f"{tag}: образец текста без кнопки"
    qbtn = last.locator(".codebox .ccopy").first
    assert "Копировать" in qbtn.inner_text(), f"{tag}: у кнопки нет подписи"
    assert qbtn.evaluate("b => getComputedStyle(b).opacity") == "1" and qbtn.is_visible(), f"{tag}: кнопка не видна"
    pg.evaluate(CLIP)
    qbtn.click()
    assert pg.evaluate("() => window.__clip") == SAMPLE, f"{tag}: образец {pg.evaluate('() => window.__clip')!r}"
    assert "Скопировано" in qbtn.inner_text(), f"{tag}: нет «Скопировано» у образца"
    code = pg.locator("#content .msg.ai .codebox:has(pre) .ccopy").first
    if code.count():
        code.scroll_into_view_if_needed()
        assert "Копировать" in code.inner_text() and code.is_visible(), f"{tag}: у блока кода нет «Копировать»"
        code.click()
        clip = pg.evaluate("() => window.__clip") or ""
        assert clip and not clip.endswith("\n"), f"{tag}: код {clip!r}"
        assert "Скопировано" in code.inner_text(), f"{tag}: нет «Скопировано» у кода"
    # (а) нажатие фразы — в поле, не отправка
    sends = pg.evaluate("() => (window.__sends = 0, window.demoApi?.run ? 1 : 0)")
    pg.locator("#content .nextq .nq").first.click()
    pg.wait_for_timeout(400)
    assert pg.input_value("#input") == PHRASES[0], f"{tag}: поле {pg.input_value('#input')!r}"
    st = pg.evaluate("() => [document.activeElement?.id, document.activeElement?.selectionStart, pending.length]")
    assert st == ["input", len(PHRASES[0]), 0], f"{tag}: курсор или отправка {st}"
    assert pg.evaluate("() => window.demoApi?.run ? 1 : 0") == sends, f"{tag}: фраза ушла в /api/send"
    assert pg.locator("#content .nq-tip").count() == 0, f"{tag}: подсказка не ушла после нажатия"
    if shots:
        pg.wait_for_timeout(300)
        pg.screenshot(path=f"{shots}/{name}-2-в-поле.png")
    # уже начали писать — фраза дописывается, не стирает
    pg.fill("#input", "Срочно:")
    pg.locator("#content .nextq .nq").nth(1).click()
    assert pg.input_value("#input") == "Срочно: " + PHRASES[1], f"{tag}: дописывание {pg.input_value('#input')!r}"
    # разбор фраз (js/nextq.js): вводная, кавычки, вопросы, код
    ps = pg.evaluate("""() => import('/js/nextq.js').then((m) => [
      m.phrases('Готово.\\n\\nМожно спросить:\\n- Сколько дублей?\\n- просто пункт\\n\\nИтог: «не фраза»'),
      m.phrases('Например, напишите «Покажи список» или «Сколько всего?»'),
      m.phrases('```\\nСпросите:\\n- «в коде»\\n```\\n- «Это вопрос?»'),
      m.phrases('Файлы:\\n- `a.py`\\n- `b.py`')])""")
    assert ps == [["Сколько дублей?"], ["Покажи список", "Сколько всего?"], ["Это вопрос?"], []], f"{tag}: разбор {ps}"


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        for eng, w, theme in (("webkit", 390, "light"), ("chromium", 1366, "dark"), ("webkit", 390, "dark"),
                              ("chromium", 1366, "light")):
            phone, tag0 = w < 600, f"{eng}-{w}-{theme}"
            br = p.webkit.launch() if eng == "webkit" else p.chromium.launch(channel="chrome", headless=True)
            kw = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True} if phone else \
                {"viewport": {"width": 1366, "height": 860}}
            for mode in ("open=@1", "focus"):
                tag = f"{tag0} {mode}"
                ctx = br.new_context(**kw)
                pg = ctx.new_page()
                pg.on("console", lambda m, tag=tag: m.type == "error" and not any(x in m.text for x in NOISE)
                      and errs.append(f"{tag}: {m.text}"))
                pg.on("pageerror", lambda e, tag=tag: errs.append(f"{tag}: {e}"))
                pg.goto(f"{base}{sep}{mode}&nq=file&theme={theme}&noscroll")
                name = f"{'фокус' if mode == 'focus' else 'чат'}-{w}-{theme}"
                check(pg, tag, phone, shots, name)
                ctx.close()
                print(f"{tag}: ок")
            br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: фразы в поле, «Копировать» у кода и образца, «Файл получен» в ленте")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo", sys.argv[2] if len(sys.argv) > 2 else "")
