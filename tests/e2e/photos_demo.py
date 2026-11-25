"""Фото в ленте и полноэкранный просмотр (владелец 16.11; Playwright).

    python tests/e2e/photos_demo.py http://127.0.0.1:8797/?demo&dev

В ленте сообщение с двумя путями к фото → две миниатюры. Нажатие — просмотр: щипок (два касания) до 5×,
двойной тап 1× ↔ 2,5×, свайп вбок — второе фото («2 из 2»), свайп вниз — закрыть; компьютер — колесо, стрелки, Esc.
Демо: картинки — заглушки без сервера (настоящие отдаёт /api/media только владельцу).
"""

import sys

import _onebrowser  # noqa: F401  — e2e с браузером по одному на сервер (tests/heavy_lock.py)

ADD = """() => { const m = document.createElement('div'); m.className = 'msg me'; m.dataset.n = '999';
  const d = '/home/u/drive/demo/Входящие/2026-11-16-';
  m.innerHTML = '<div class="bubble">Посмотри фото.\\n\\nФайл из панели: ' + d + 'стенд.jpg'
    + '\\nФайл из панели: ' + d + 'щит.png</div>';
  document.getElementById('content').append(m); }"""

def open_photo(pg, idx: int) -> None:
    """Вставить сообщение с фото и открыть idx-ю миниатюру. Лента демо обновляется по таймеру и может стереть
    вставленное сообщение (элемент «detached» — CI 16.11), поэтому нажатие — в том же шаге JS, что и проверка, с
    повтором вставки."""
    for _ in range(5):
        pg.evaluate(ADD)
        try:
            pg.wait_for_function(
                f"(() => {{ const a = document.querySelectorAll('.att-imgs img[src]');"
                f" if (a.length !== 2) return false; a[{idx}].click(); return true; }})()", timeout=5000)
        except Exception:
            continue
        if pg.locator(".lb img[src]").count() or pg.wait_for_selector(".lb img[src]", timeout=3000):
            return
    raise AssertionError("миниатюры не открылись")



def ptr(pg, kind, pid, x, y):
    pg.evaluate("([k, id, x, y]) => document.querySelector('.lb').dispatchEvent(new PointerEvent(k, {"
                "pointerId: id, clientX: x, clientY: y, bubbles: true, pointerType: 'touch', isPrimary: id === 1}))",
                [kind, pid, x, y])


def scale(pg) -> float:
    return pg.evaluate("(() => { const m = getComputedStyle(document.querySelector('.lb img')).transform;"
                       " return m === 'none' ? 1 : new DOMMatrix(m).a; })()")


def run(base: str):
    from playwright.sync_api import sync_playwright

    sep = "&" if "?" in base else "?"
    errs: list[str] = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        # телефон
        ctx = br.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{base}{sep}open=@1&noscroll")
        pg.wait_for_selector("#content .msg")
        pg.wait_for_function("!!window.lightbox", timeout=8000)
        open_photo(pg, 0)
        assert pg.inner_text(".lb-n") == "1 из 2"
        cx, cy = 195, 422
        ptr(pg, "pointerdown", 1, cx - 40, cy)                              # щипок — развести пальцы
        ptr(pg, "pointerdown", 2, cx + 40, cy)
        for k in range(1, 6):
            ptr(pg, "pointermove", 1, cx - 40 - k * 20, cy)
            ptr(pg, "pointermove", 2, cx + 40 + k * 20, cy)
        ptr(pg, "pointerup", 1, cx - 140, cy)
        ptr(pg, "pointerup", 2, cx + 140, cy)
        assert scale(pg) > 2, f"щипок: {scale(pg)}"
        for _ in range(2):                                                   # двойной тап — снова 1×
            ptr(pg, "pointerdown", 1, cx, cy)
            ptr(pg, "pointerup", 1, cx, cy)
        assert abs(scale(pg) - 1) < 0.01, "двойной тап не вернул 1×"
        pg.wait_for_timeout(400)
        ptr(pg, "pointerdown", 1, 300, cy)                                   # свайп влево — следующее фото
        ptr(pg, "pointermove", 1, 150, cy)
        ptr(pg, "pointerup", 1, 150, cy)
        assert pg.inner_text(".lb-n") == "2 из 2", "свайп вбок не перелистнул"
        ptr(pg, "pointerdown", 1, cx, 300)                                   # свайп вниз — закрыть
        ptr(pg, "pointermove", 1, cx, 500)
        ptr(pg, "pointerup", 1, cx, 500)
        assert pg.locator(".lb").count() == 0, "свайп вниз не закрыл"
        ctx.close()
        # компьютер: колесо, стрелки, Esc
        pg = br.new_page(viewport={"width": 1366, "height": 860})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{base}{sep}open=@1&noscroll")
        pg.wait_for_selector("#content .msg")
        pg.wait_for_function("!!window.lightbox", timeout=8000)
        open_photo(pg, 1)
        assert pg.inner_text(".lb-n") == "2 из 2"
        pg.mouse.move(683, 430)
        for _ in range(3):
            pg.mouse.wheel(0, -200)
        assert scale(pg) > 2, f"колесо: {scale(pg)}"
        pg.keyboard.press("ArrowRight")
        assert pg.inner_text(".lb-n") == "1 из 2" and abs(scale(pg) - 1) < 0.01
        pg.keyboard.press("Escape")
        assert pg.locator(".lb").count() == 0
        br.close()
    assert not errs, f"ошибки: {errs}"
    print("ok: фото в ленте — миниатюры, просмотр: щипок, двойной тап, свайпы, колесо, стрелки, Esc")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo&dev")
