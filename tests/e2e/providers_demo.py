"""Что работает у поставщика и автотест поставщиков (задача 38; Playwright, демо-режим).

    python tests/e2e/providers_demo.py "http://127.0.0.1:8797/?demo" [папка-для-скриншотов]

Телефон 390 и ПК 1366, светлая и тёмная тема:
- сессия DeepSeek (``open=@4``) — плашка «DeepSeek: недоступно — …», «Подробнее» открывает список, «×» скрывает;
- «Настройки» → «Поставщики» (``prov``) — карточки с проверками, «Проверить сейчас» → «идёт» → итог;
- «Интеграции» — разделы «Для любой модели» (с отметкой «все поставщики») и «Через сайт Claude»;
- коннектор Notion (``conn=notion``) — замена через сервер; выбор поставщика (``pick=1``) — «недоступно: …».
Консоль без ошибок, без горизонтальной прокрутки.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def screen(page, w: int, theme: str, base: str, out: Path | None):
    sep = "&" if "?" in base else "?"

    def go(q, shot):
        page.goto(f"{base}{sep}theme={theme}&{q}")
        page.wait_for_timeout(1300)
        wide = page.evaluate("document.documentElement.scrollWidth - innerWidth")
        assert wide <= 1, (q, w, wide)
        if out:
            page.screenshot(path=str(out / f"{shot}-{w}-{theme}.png"))

    go("open=@4", "gap-session")
    bar = page.locator("#gapBar")
    assert bar.is_visible() and "DeepSeek" in bar.inner_text() and "картинки" in bar.inner_text()
    page.click("#gapBar [data-gap-more]")
    page.wait_for_timeout(300)
    assert "Работает" in page.inner_text("#mcpForm") and "WebSearch" in page.inner_text("#mcpForm")
    if out:
        page.screenshot(path=str(out / f"gap-more-{w}-{theme}.png"))
    page.click("#backBtn")
    page.wait_for_timeout(500)
    page.click("#gapBar [data-gap-hide]")
    assert page.locator("#gapBar").count() == 0
    page.evaluate("localStorage.removeItem('gaps:deepseek')")

    go("prov", "providers")
    txt = page.inner_text("#mcpForm")
    assert "GLM (Z.ai)" in txt and "чтение страницы" in txt and "Проверить сейчас" in txt
    page.click("#stRun")
    page.wait_for_timeout(600)
    assert "Проверка идёт" in page.inner_text("#mcpForm")
    page.wait_for_timeout(9500)
    assert "Проверить сейчас" in page.inner_text("#mcpForm")
    if out:
        page.screenshot(path=str(out / f"providers-done-{w}-{theme}.png"), full_page=True)

    go("view=integrations", "integrations")
    page.wait_for_timeout(600)
    txt = page.inner_text("#integrationsView").lower()        # заголовки разделов — заглавными
    assert "для любой модели" in txt and "все поставщики" in txt and "через сайт claude" in txt
    assert "веб-поиск tavily" in txt and "google диск" in txt

    go("conn=notion", "connector")
    assert "через сервер" in page.inner_text("#mcpForm")
    go("pick=1", "pick")
    assert "недоступно:" in page.inner_text(".sheet")
    go("prof=zai", "provider-form")
    assert "На этом поставщике недоступно" in page.inner_text("#mcpForm")


def main(base: str, out: Path | None):
    errors = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(channel="chrome")
        for w, h in ((390, 844), (1366, 900)):
            for theme in ("light", "dark"):
                ctx = b.new_context(viewport={"width": w, "height": h})
                page = ctx.new_page()
                tag = f"{w}/{theme}"
                page.on("console", lambda m, tag=tag: m.type == "error" and "404" not in m.text   # значок вкладки
                        and errors.append(f"{tag}: {m.text}"))
                page.on("pageerror", lambda e, tag=tag: errors.append(f"{tag}: {e}"))
                screen(page, w, theme, base, out)
                ctx.close()
        b.close()
    assert not errors, errors
    print("ok: плашка, «Поставщики», «Интеграции», коннектор, выбор поставщика — 390/1366, светлая/тёмная")


if __name__ == "__main__":
    o = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if o:
        o.mkdir(parents=True, exist_ok=True)
    main(sys.argv[1], o)
