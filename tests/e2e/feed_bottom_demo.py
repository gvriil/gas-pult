"""Лента держит низ при ресайзе, если вы были внизу (#189, UI/UX п.4; Playwright — pytest запускает, только если
есть браузер).

    python tests/e2e/feed_bottom_demo.py http://127.0.0.1:8797/?demo

Демо @3: прошло 4 с после открытия (окно «прилипания» закончилось) — окно стало ниже (клавиатура, поворот) и
черновик в поле вырос на несколько строк — лента у последнего сообщения. Пролистали вверх — ресайз не тянет вниз.
Телефон 390 и компьютер 1366, светлая и тёмная тема, консоль без ошибок.
"""

import sys

import _onebrowser  # noqa: F401  — e2e с браузером по одному на сервер (tests/heavy_lock.py)

GAP = "() => { const s = document.getElementById('scroller'); return s.scrollHeight - s.clientHeight - s.scrollTop; }"


def run(base: str):
    from playwright.sync_api import sync_playwright

    sep = "&" if "?" in base else "?"
    errs: list[str] = []
    with sync_playwright() as p:
        br = p.chromium.launch()
        for w, h, th in ((390, 844, "dark"), (1366, 860, "light"), (390, 844, "light"), (1366, 860, "dark")):
            where = f"{w} {th}"
            pg = br.new_page(viewport={"width": w, "height": h}, color_scheme=th)
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.add_init_script("() => { try { localStorage.setItem('gp:tourDone', '1'); } catch (e) {} }")
            pg.goto(f"{base}{sep}theme={th}")
            pg.wait_for_function("() => typeof openSession === 'function' && sessions.length")
            pg.evaluate("() => openSession('@3')")
            pg.wait_for_selector('#content .msg[data-i="11"]')
            pg.wait_for_timeout(4500)                                    # «прилипание» после открытия кончилось
            assert pg.evaluate(GAP) <= 24, f"{where}: после открытия не внизу ({pg.evaluate(GAP)})"
            pg.set_viewport_size({"width": w, "height": h - 300})       # клавиатура или окно ниже
            pg.wait_for_timeout(300)
            assert pg.evaluate(GAP) <= 24, f"{where}: ресайз сдвинул от низа ({pg.evaluate(GAP)})"
            pg.fill("#input", "\n".join(f"строка {i}" for i in range(6)))  # черновик растёт — док выше
            pg.wait_for_timeout(300)
            assert pg.evaluate(GAP) <= 24, f"{where}: черновик сдвинул от низа ({pg.evaluate(GAP)})"
            pg.fill("#input", "")
            pg.evaluate("() => { const s = document.getElementById('scroller'); s.scrollTop -= 400; }")
            pg.wait_for_timeout(200)
            assert pg.evaluate(GAP) > 150, f"{where}: не пролистали вверх ({pg.evaluate(GAP)})"
            pg.set_viewport_size({"width": w, "height": h - 400})
            pg.wait_for_timeout(300)
            assert pg.evaluate(GAP) > 150, f"{where}: читали выше — ресайз утянул вниз ({pg.evaluate(GAP)})"
            pg.close()
        br.close()
    assert not errs, errs


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo")
    print("ok")
