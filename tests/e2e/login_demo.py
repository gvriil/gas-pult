"""Шторка «Нужен вход» в демо (Playwright).

    python tests/e2e/login_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Окно @1 просит войти (?login=gh|claude|mcp): шторка открывается сама — ① код с «Копировать» (GitHub), ② «Открыть
ссылку», ③ поле «В окно» (Claude — код со страницы, MCP — адрес после входа), «Готово — проверить». Закрыли — тот же
вход больше не навязывается. Фокус-ссылка — без шторки. 390 и 1366, светлая и тёмная, консоль без ошибок.
"""

import sys


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for w, theme in ((390, "light"), (1366, "dark"), (390, "dark"), (1366, "light")):
            tag = f"{w}/{theme}"
            kw = {"viewport": {"width": w, "height": 844}}
            if w == 390:
                kw |= {"is_mobile": True, "has_touch": True}
            ctx = br.new_context(**kw)
            ctx.add_init_script("try { localStorage.setItem('gp:tourDone', '1'); } catch (e) {}")
            ctx.grant_permissions(["clipboard-read", "clipboard-write"])
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))

            # GitHub: код устройства — показать и скопировать; вводить в окно нечего
            pg.goto(f"{base}{sep}open=@1&login=gh&theme={theme}&noscroll")
            pg.wait_for_selector(".login-bg .sheet", timeout=8000)
            sh = pg.locator(".login-bg .sheet")
            assert "нужен вход: github" in sh.inner_text().lower(), tag
            assert sh.locator("#loginOtp").inner_text() == "AB12-CD34", tag
            assert sh.locator("[data-la=open]").is_visible() and "github.com/login/device" in sh.inner_text()
            assert sh.locator("#loginIn").count() == 0, f"{tag}: GitHub не ждёт ввода в окно"
            assert pg.locator(".login-bg").get_attribute("data-help") == "sheet.login"
            sh.locator("[data-la=copy]").click()
            pg.wait_for_selector(".toast:has-text('Код скопирован')", timeout=3000)
            if shots:
                pg.screenshot(path=f"{shots}/login-gh-{w}-{theme}.png")
            sh.locator("[data-la=check]").click()
            pg.wait_for_selector("#loginRes .result.bad", timeout=3000)
            pg.click(".login-bg [data-close]")
            pg.wait_for_timeout(3500)                           # опрос экрана: тот же вход снова не навязываем
            assert pg.locator(".login-bg").count() == 0, f"{tag}: закрытая шторка вернулась"

            # Claude: код со страницы — в окно, проверка — вход выполнен, шторка закрывается
            pg.goto(f"{base}{sep}open=@1&login=claude&theme={theme}&noscroll")
            pg.wait_for_selector(".login-bg #loginIn", timeout=8000)
            sh = pg.locator(".login-bg .sheet")
            assert "нужен вход: claude" in sh.inner_text().lower() and sh.locator("#loginOtp").count() == 0, tag
            sh.locator("[data-la=send]").click()
            pg.wait_for_selector(".toast:has-text('Вставьте код')", timeout=3000)
            sh.locator("#loginIn").fill("demo#code_123")
            sh.locator("[data-la=send]").click()
            pg.wait_for_selector(".toast:has-text('Отправлено в окно')", timeout=3000)
            assert sh.locator("#loginIn").input_value() == "", f"{tag}: код остался в поле"
            if shots:
                pg.screenshot(path=f"{shots}/login-claude-{w}-{theme}.png")
            sh.locator("[data-la=check]").click()
            pg.wait_for_selector("#loginRes .result.ok", timeout=3000)
            pg.wait_for_selector(".login-bg", state="detached", timeout=4000)

            # MCP: адрес страницы после входа
            pg.goto(f"{base}{sep}open=@1&login=mcp&theme={theme}&noscroll")
            pg.wait_for_selector(".login-bg #loginIn", timeout=8000)
            assert "localhost" in pg.locator(".login-bg #loginIn").get_attribute("placeholder"), tag
            ctx.close()

        # фокус-ссылка — шторки нет
        ctx = br.new_context(viewport={"width": 1366, "height": 860})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{base}{sep}focus&login=gh&theme=dark&noscroll")
        pg.wait_for_timeout(3000)
        assert pg.locator(".login-bg").count() == 0, "фокус: шторка входа показана"
        ctx.close()
        br.close()
    assert not errs, errs
    print("login_demo ok")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
