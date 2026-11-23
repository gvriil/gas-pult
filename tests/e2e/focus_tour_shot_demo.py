"""Тур фокус-чата и снимок экрана к отчёту об ошибке (Playwright; задача владельца 23.11).

    python tests/e2e/focus_tour_shot_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Демо фокус-ссылки (``&focus``): «⋯» → «Тур по экрану» — тур фокуса (js/focustour.js) проходит все шаги до «Готово»
и закрывается; без вопроса на экране шаг «Кнопки вариантов» — попап по центру. «Сообщить об ошибке» → миниатюра
снимка (JPEG, ширина ≤ 1280, ≤ 400 КБ) → «Отправить» → в /api/bug (демо: ``demoApi.bugs``) пришёл файл снимка.
«Убрать снимок» — уходит без снимка, со строкой «снимок убрал человек». CDN закрыт — «Снимок не получился», отчёт
уходит с описанием. Тег скрипта библиотеки — с integrity и crossorigin. Плашка ``data-no-shot`` закрыта на снимке.
Движки: WebKit 390 (телефон) и Chromium 1366; светлая и тёмная тема; консоль без ошибок.

Нет сети до CDN — подставьте локальные копии (в репозиторий их не кладём): ``GP_SHOT_LIB=<modern-screenshot index.js>``,
``GP_DRIVER_JS=<driver.js.iife.min.js>``, ``GP_DRIVER_CSS=<driver.min.css>``. SRI проверяет браузер и в этом случае:
копия должна совпадать байт в байт.
"""

import base64
import os
import sys

import _onebrowser  # noqa: F401  — e2e с браузером по одному на сервер (tests/heavy_lock.py)

SHOT_URL = "https://cdn.jsdelivr.net/npm/modern-screenshot@4.7.0/dist/index.js"
DRIVER = "https://cdnjs.cloudflare.com/ajax/libs/driver.js/1.8.0/"
LOCAL = {SHOT_URL: ("GP_SHOT_LIB", "application/javascript"),
         DRIVER + "driver.js.iife.min.js": ("GP_DRIVER_JS", "application/javascript"),
         DRIVER + "driver.min.css": ("GP_DRIVER_CSS", "text/css")}
CORS = {"Access-Control-Allow-Origin": "*"}


def local_copies(ctx):
    for url, (env, ctype) in LOCAL.items():
        if os.environ.get(env):
            with open(os.environ[env], "rb") as f:
                body = f.read()
            ctx.route(url, lambda r, b=body, t=ctype: r.fulfill(status=200, body=b, content_type=t, headers=CORS))


# плашка data-no-shot (красная, с цифрами) и поле пароля — на снимке должны быть закрыты
SECRET = """document.body.insertAdjacentHTML("beforeend", `<div id="secretBox" style="position:fixed;left:0;top:200px;
  width:120px;z-index:5"><div data-no-shot style="height:60px;background:rgb(255,0,0);font:700 40px sans-serif;
  color:#000">1234</div><input type="password" value="WWWWWW" style="display:block;width:120px;height:60px;border:0;
  font:700 40px sans-serif;color:#000;background:#fff"></div>`)"""
# миниатюра: тип, размер, ширина; по плашке и паролю — разброс яркости и число красных точек
PIX = """async () => { const u = document.getElementById("bugPrev").src;
  const im = new Image(); im.src = u; await im.decode();
  const c = document.createElement("canvas"); c.width = im.width; c.height = im.height;
  const g = c.getContext("2d"); g.drawImage(im, 0, 0);
  const k = im.width / document.body.clientWidth, top = document.body.getBoundingClientRect().top;
  const box = (y) => {
    const d = g.getImageData(Math.round(8 * k), Math.round((y - top) * k), Math.round(104 * k),
      Math.round(44 * k)).data;
    let lo = 255, hi = 0, red = 0;
    for (let i = 0; i < d.length; i += 4) {
      const v = (d[i] + d[i + 1] + d[i + 2]) / 3; lo = Math.min(lo, v); hi = Math.max(hi, v);
      if (d[i] > 200 && d[i + 1] < 80) red++;
    }
    return [hi - lo, red]; };
  return { kind: u.slice(0, 15), bytes: (u.length - 23) * 0.75, w: im.width, div: box(208), pwd: box(268) }; }"""
SHOT_TAG = """(() => { const s = document.querySelector("script[data-lib=shot]");
  return s && [s.src, s.integrity, s.crossOrigin]; })()"""
NOISE = ("404", "interactive-widget")            # WebKit: «interactive-widget» в meta viewport ему не известен


def walk(pg, w: int, shots: str, name: str) -> list[str]:
    seen: list[str] = []
    for _ in range(12):
        pg.wait_for_selector(".driver-popover.gp-tour", timeout=8000)
        pg.wait_for_timeout(400)
        title = pg.inner_text(".driver-popover-title")
        box = pg.locator(".driver-popover").bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= w + 0.5, f"{name} «{title}»: попап за краем {box}"
        if shots and len(seen) in (0, 1):
            pg.screenshot(path=f"{shots}/{name}-{len(seen) + 1}.png")
        seen.append(title)
        nxt = pg.inner_text(".driver-popover-next-btn")
        pg.click(".driver-popover-next-btn")
        if nxt == "Готово":
            pg.wait_for_selector(".driver-popover", state="detached")
            return seen
    raise AssertionError(f"{name}: тур не закончился: {seen}")


def open_bug(pg, phone: bool):
    if phone:
        pg.click("#menuBtn")
        pg.click("#menu [data-act=bug]")
    else:
        pg.click("#bugBtn")
    pg.wait_for_selector("#bugTitle")


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        for eng, w, theme in (("webkit", 390, "light"), ("chromium", 1366, "dark"), ("webkit", 390, "dark"),
                              ("chromium", 1366, "light")):
            phone, tag = w < 600, f"{eng}-{w}-{theme}"
            br = (p.webkit.launch() if eng == "webkit" else p.chromium.launch(channel="chrome", headless=True))
            kw = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True} if phone else \
                {"viewport": {"width": 1366, "height": 860}}
            ctx = br.new_context(**kw)
            local_copies(ctx)

            def page(q, ctx=ctx, tag=tag):
                pg = ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and not any(x in m.text for x in NOISE)
                      and errs.append(f"{tag}: {m.text}"))
                pg.on("pageerror", lambda e: errs.append(f"{tag}: {e}"))
                pg.goto(q)
                pg.wait_for_selector("#session:not([hidden])")
                pg.wait_for_timeout(1200)
                return pg

            ask = "&ask=question" if theme == "light" else ""      # с вопросом и без: шаг «Кнопки вариантов»
            pg = page(f"{base}{sep}focus{ask}&theme={theme}&noscroll")

            # «⋯» → «Тур по экрану»
            pg.click("#chatMoreBtn")
            pg.locator(".sheet button", has_text="Тур по экрану").click()
            seen = walk(pg, w, shots, f"tour-{tag}")
            for t in ("Поле ввода", "Кнопки вариантов", "Сообщить об ошибке", "На другом устройстве", "Чаты",
                      "Меню «⋯»"):
                assert t in seen, f"{tag}: нет шага «{t}»: {seen}"
            assert pg.evaluate("tourOn") is False, f"{tag}: тур не закрылся"
            assert pg.locator(".driver-overlay").count() == 0, f"{tag}: подсветка тура осталась"
            assert pg.evaluate("localStorage.getItem('gp.ftour:f1')") == "done", f"{tag}: нет отметки тура"
            drv = pg.evaluate("[...document.scripts].find((s) => s.src.includes('driver.js'))?.integrity || ''")
            assert drv.startswith("sha512-"), f"{tag}: driver.js без integrity"

            # отчёт: снимок сам → миниатюра → отправка → файл в /api/bug
            pg.evaluate(SECRET)
            open_bug(pg, phone)
            pg.wait_for_selector("#bugPrev:not([hidden])", timeout=20000)
            src = pg.evaluate(SHOT_TAG)
            assert src and src[0] == SHOT_URL and src[1].startswith("sha512-") and src[2] == "anonymous", src
            info = pg.evaluate(PIX)
            assert info["kind"] == "data:image/jpeg" and info["bytes"] <= 400 * 1024 and info["w"] <= 1280, info
            if shots:
                u = pg.evaluate("document.getElementById('bugPrev').src")
                with open(f"{shots}/shot-{tag}.jpg", "wb") as f:
                    f.write(base64.b64decode(u.split(",", 1)[1]))
            # закрытое — ровная плашка: ни красного фона, ни текста (разброс яркости — только шум JPEG)
            assert info["div"][1] == 0 and info["div"][0] < 40, f"{tag}: data-no-shot видно на снимке {info['div']}"
            assert info["pwd"][0] < 40, f"{tag}: пароль виден на снимке {info['pwd']}"
            assert "приложится сам" in pg.inner_text("#bugShotNote") and pg.is_visible("#bugDrop")
            assert "паролей и кодов" in pg.inner_html(".sheet details")
            pg.fill("#bugText", "Кнопка не нажимается")
            pg.click("#bugGo")
            pg.wait_for_selector("#bugTitle", state="detached")
            sent = pg.evaluate("demoApi.bugs.at(-1)")
            assert sent["w"] == "@1" and sent["shot"].startswith("data:image/jpeg;base64,"), f"{tag}: снимок не ушёл"
            assert not sent["ctx"].get("shot_note"), sent["ctx"]

            # «Убрать снимок» — уходит без снимка, с честной строкой
            pg.evaluate("document.getElementById('secretBox').remove()")
            open_bug(pg, phone)
            pg.wait_for_selector("#bugDrop:not([hidden])", timeout=20000)
            if shots:
                pg.fill("#bugText", "Нажал «Отправить», а фото не ушло")
                pg.wait_for_timeout(300)
                pg.screenshot(path=f"{shots}/bug-{tag}.png")
            pg.click("#bugDrop")
            assert pg.is_hidden("#bugPrev") and "убран" in pg.inner_text("#bugShotNote")
            pg.fill("#bugText", "Без снимка")
            pg.click("#bugGo")
            pg.wait_for_selector("#bugTitle", state="detached")
            sent = pg.evaluate("demoApi.bugs.at(-1)")
            assert sent["shot"] == "" and sent["ctx"]["shot_note"] == "снимок убрал человек", sent["ctx"]
            pg.close()

            # CDN закрыт — «Снимок не получился», отчёт уходит с описанием
            ctx.route(SHOT_URL, lambda r: r.abort())
            pg = page(f"{base}{sep}focus&theme={theme}&noscroll")
            open_bug(pg, phone)
            pg.wait_for_function("document.getElementById('bugShotNote').textContent.includes('не получился')",
                                 timeout=15000)
            assert pg.is_hidden("#bugPrev")
            pg.fill("#bugText", "Без сети")
            pg.click("#bugGo")
            pg.wait_for_selector("#bugTitle", state="detached")
            sent = pg.evaluate("demoApi.bugs.at(-1)")
            assert sent["shot"] == "" and "снимок не получился" in sent["ctx"]["shot_note"], sent["ctx"]
            assert sent["ctx"]["screen"] and sent["ctx"]["size"], sent["ctx"]
            pg.close()
            ctx.close()
            br.close()
    # CDN закрыт — браузер пишет в консоль «не загрузился скрипт»: это проверка, не ошибка панели
    errs = [e for e in errs if "modern-screenshot" not in e and "Failed to load resource" not in e]
    assert not errs, f"ошибки консоли: {errs}"


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    print("focus_tour_shot_demo ok")
