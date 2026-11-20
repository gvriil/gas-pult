"""Поворот телефона (владелец 20.11): «повернул — вижу то же место».

Демо, iPhone 13, 390×844 ↔ 844×390: длинный чат — середина (то же сообщение на том же месте) и низ (остаться
внизу); шторка, панель чатов, меню у строки и поле ввода при повороте не закрываются и не сбрасываются.
"""
from playwright.sync_api import sync_playwright

ANCH = """() => { const sc = document.getElementById('scroller'), top = sc.getBoundingClientRect().top;
  const ms = [...document.querySelectorAll('#content .msg[data-i]')];
  const m = ms.find((x) => x.getBoundingClientRect().top >= top - 1)
    || ms.findLast((x) => x.getBoundingClientRect().top < top);
  return { i: m?.dataset.i, off: m ? Math.round(m.getBoundingClientRect().top - top) : null,
           bottom: Math.round(sc.scrollHeight - sc.clientHeight - sc.scrollTop) }; }"""
AT = """(i) => { const sc = document.getElementById('scroller');
  const m = document.querySelector(`#content .msg[data-i="${i}"]`);
  return m ? Math.round(m.getBoundingClientRect().top - sc.getBoundingClientRect().top) : null; }"""
LONG = """() => { const h = demoApi.h, L = 'Длинный абзац ответа, который при повороте переносится иначе. '.repeat(8);
  const base = Math.max(...h.map((x) => x.i || 0)) + 1;
  for (let k = 0; k < 40; k++)
    h.push({ ...h[h.length - 1], i: base + k, role: k % 2 ? 'assistant' : 'user', text: k % 2 ? L : 'Вопрос ' + k });
  hist = []; loadContent(); }"""
LAND, PORT = {"width": 844, "height": 390}, {"width": 390, "height": 844}


def run(url: str):
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        pg = b.new_context(**p.devices["iPhone 13"]).new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(url)
        pg.wait_for_timeout(2500)
        pg.evaluate("openSession('@1')")
        pg.wait_for_timeout(2000)
        pg.evaluate(LONG)
        pg.wait_for_timeout(5500)                                    # «прилипнуть к низу» после открытия — 4 с
        pg.mouse.move(195, 400)
        for case, dy in (("середина", -2500), ("середина", -700), ("середина", 400), ("низ", 20000)):
            pg.mouse.wheel(0, dy)
            pg.wait_for_timeout(600)
            a = pg.evaluate(ANCH)
            pg.set_viewport_size(LAND)
            pg.wait_for_timeout(900)
            land = pg.evaluate(ANCH)
            at_land = pg.evaluate(AT, a["i"])
            pg.set_viewport_size(PORT)
            pg.wait_for_timeout(900)
            back = pg.evaluate(ANCH)
            at_back = pg.evaluate(AT, a["i"])
            if case == "середина":                                   # то же сообщение — на том же месте
                assert abs((at_land or 1e9) - a["off"]) <= 4, ("поворот сдвинул ленту", a, at_land, land)
                assert abs((at_back or 1e9) - a["off"]) <= 4, ("назад сдвинул ленту", a, at_back, back)
            else:
                assert land["bottom"] <= 4 and back["bottom"] <= 4, ("поворот увёл от низа", a, land, back)
        # шторка с прокруткой внутри
        pg.evaluate("go('go:settings.legend')")
        pg.wait_for_timeout(800)
        pg.evaluate("document.querySelector('.sheet').scrollTop = 120")
        before = pg.evaluate("document.querySelector('.sheet').scrollTop")
        pg.set_viewport_size(LAND)
        pg.wait_for_timeout(700)
        after = (pg.locator(".sheet").count(), pg.evaluate("document.querySelector('.sheet').scrollTop"))
        assert after[0] == 1 and abs(after[1] - before) <= 16, (before, after)     # шторка ниже — сдвиг, не сброс
        pg.set_viewport_size(PORT)
        pg.evaluate("document.querySelectorAll('.sheet-bg').forEach((x) => x.remove())")
        # панель чатов и меню у строки
        pg.click("#navBtn")
        pg.wait_for_timeout(500)
        pg.locator("#navList .nrow[data-nw]").first.dispatch_event("contextmenu")
        pg.wait_for_timeout(300)
        pg.set_viewport_size(LAND)
        pg.wait_for_timeout(700)
        assert pg.evaluate("document.body.classList.contains('nav-open')"), "панель закрылась при повороте"
        bb = pg.locator(".pop").bounding_box()
        assert bb and bb["x"] >= 0 and bb["x"] + bb["width"] <= 844 and bb["y"] + bb["height"] <= 390, bb
        pg.set_viewport_size(PORT)
        pg.evaluate("closePop(); navOpen(false)")
        # поле ввода
        pg.fill("#input", "черновик")
        pg.focus("#input")
        pg.set_viewport_size(LAND)
        pg.wait_for_timeout(700)
        assert pg.evaluate("document.activeElement.id") == "input" and pg.input_value("#input") == "черновик"
        b.close()
    assert not errs, errs
