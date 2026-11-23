"""Термины в анкете /q/ (TGI через штаб, 23.11; Playwright).

    python tests/e2e/forms_glossary_demo.py [папка-для-снимков] [анкета.json]

Без адреса — поднимает настоящую панель во временной папке (своя CSP, как в бою), кладёт демо-анкету (или копию
указанной ``анкета.json``) и делает личную ссылку. WebKit 390 (касание) и Chromium 1366, светлая и тёмная тема:
  (а) нажатие на термин открывает пояснение (role="tooltip", aria-expanded, aria-describedby), окно не выходит за
      край экрана; повторное нажатие закрывает; нажатие мимо закрывает; Esc закрывает и возвращает фокус;
      Enter открывает, Space закрывает; одно окно за раз;
  (б) термин внутри варианта ответа — радио и флажок — не меняет выбор; нажатие на сам вариант — меняет;
  (в) консоль без ошибок.
"""

import json
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

DEMO = {
    "id": "demo-glossary", "title": "Учёт имущества: демо терминов",
    "intro": "Ответьте на вопросы про ОС и метки — так мы покажем решение под вас.",
    "rules": ["Точные числа не нужны: хватит порядка, как в инвентаризационной описи."],
    "finish": "Спасибо!",
    "glossary": {
        "ОС": "Основные средства — то, что служит больше года: мебель, техника, оборудование.",
        "основные средства": "То, что служит больше года и стоит на балансе: мебель, техника, оборудование.",
        "метки": "Наклейки с кодом на предметах: навели телефон — и видно, что это и где стоит.",
        "МОЛ": "Материально ответственное лицо — сотрудник, который отвечает за сохранность вещей.",
        "инвентаризационной описи": "Список вещей с отметками «есть» или «нет» — его заполняют при проверке.",
        "QR": "Квадратный код, который читает камера любого телефона.",
        "NFC": "Метка, которую телефон читает, если поднести его вплотную.",
    },
    "sections": [{"id": "s1", "title": "Что учитываем", "questions": [
        {"id": "kind", "text": "Сколько ОС на балансе — примерно? Считайте основные средства целиком, вместе с МОЛ",
         "hint": "От этого зависит, сколько нужно метки и сколько времени займёт первая наклейка.",
         "options": ["До 1 000", "1 000–10 000", "Больше 10 000 ОС"], "required": True},
        {"id": "tags", "text": "Какие метки удобнее?", "multi": True,
         "options": ["QR-наклейки", "NFC-метки", "Пока не знаю"]},
    ]}],
}


def link(panel, form: dict) -> str:
    """Положить анкету в данные панели и выдать личную ссылку /q/<код>."""
    d = panel.cfg.data / "forms"
    d.mkdir(exist_ok=True)
    (d / f"{form['id']}.json").write_text(json.dumps(form, ensure_ascii=False), encoding="utf-8")
    return panel.forms_links.new(form["id"], "Демо")["path"]


def _tip_ok(pg, tag: str, term: str):
    tip = pg.locator("#gltip")
    assert tip.is_visible(), f"{tag}: пояснение к «{term}» не открылось"
    b = pg.locator(".gl[aria-expanded='true']")
    assert b.count() == 1, f"{tag}: открыто окон: {b.count()}"
    assert b.get_attribute("aria-describedby") == "gltip" and tip.get_attribute("role") == "tooltip"
    box, vw = tip.bounding_box(), pg.evaluate("document.documentElement.clientWidth")
    assert box["x"] >= 0 and box["x"] + box["width"] <= vw + 0.5, f"{tag}: окно за краем {box} при ширине {vw}"
    assert pg.evaluate("document.documentElement.scrollWidth - innerWidth") <= 1, f"{tag}: страница шире экрана"


def _closed(pg, tag: str, why: str):
    pg.wait_for_timeout(100)
    assert not pg.locator("#gltip").is_visible(), f"{tag}: {why} — окно не закрылось"
    assert pg.locator(".gl[aria-expanded='true']").count() == 0, f"{tag}: {why} — aria-expanded остался"


def check(pg, tag: str, phone: bool, shots: str, name: str, demo: bool):
    press = (lambda loc: loc.tap()) if phone else (lambda loc: loc.click())
    pg.wait_for_selector("#next:text('Начать')", timeout=10000)
    if shots:
        pg.screenshot(path=f"{shots}/{name}-0-вступление.png")
    if not demo:                                       # чужая анкета: первый термин, где бы он ни был
        press(pg.locator("#next"))
        g = pg.locator(".gl:visible").first
        g.wait_for(timeout=5000)
        g.scroll_into_view_if_needed()
        press(g)
        _tip_ok(pg, tag, g.inner_text())
        if shots:
            pg.screenshot(path=f"{shots}/{name}-1-термин.png")
        return
    intro = pg.locator("#app p .gl").first
    press(intro)
    _tip_ok(pg, tag, "intro")
    assert "Основные средства" in pg.locator("#gltip").inner_text()
    press(pg.locator("#next"))
    pg.wait_for_selector("#q-kind")
    # (а) термин в тексте вопроса: открыть, закрыть повторным нажатием, нажатием мимо, Esc
    h = pg.locator("#q-kind h3 .gl", has_text="ОС").first
    press(h)
    _tip_ok(pg, tag, "ОС")
    assert pg.locator("#gltip strong").inner_text() == "ОС"
    if shots:
        pg.screenshot(path=f"{shots}/{name}-1-термин-в-вопросе.png")
    press(h)
    _closed(pg, tag, "повторное нажатие")
    press(h)
    _tip_ok(pg, tag, "ОС")
    press(pg.locator("h2"))
    _closed(pg, tag, "нажатие мимо")
    last = pg.locator("#q-kind h3 .gl", has_text="МОЛ")          # термин в конце строки — у правого края
    press(last)
    _tip_ok(pg, tag, "МОЛ")
    press(pg.locator("#q-kind h3 .gl", has_text="основные средства"))   # другой термин — окно одно
    _tip_ok(pg, tag, "основные средства")
    pg.keyboard.press("Escape")
    _closed(pg, tag, "Esc")
    assert pg.evaluate("document.activeElement.textContent") == "основные средства", f"{tag}: фокус не вернулся"
    pg.keyboard.press("Enter")                         # с клавиатуры: Enter открыл, Space закрыл
    _tip_ok(pg, tag, "Enter")
    pg.keyboard.press(" ")
    _closed(pg, tag, "Space")
    # термин в «Зачем спрашиваем»
    press(pg.locator("#q-kind summary"))
    press(pg.locator("#q-kind .why .gl"))
    _tip_ok(pg, tag, "hint")
    # (б) радио: термин в варианте не выбирает, сам вариант — выбирает, термин после выбора — не снимает
    opt = pg.locator("#q-kind .opt").nth(2)
    radio = opt.locator(".pick")
    press(opt.locator(".gl"))
    _tip_ok(pg, tag, "ОС в варианте")
    assert radio.get_attribute("aria-checked") == "false", f"{tag}: термин выбрал радио"
    if shots:
        opt.scroll_into_view_if_needed()
        pg.screenshot(path=f"{shots}/{name}-2-термин-в-варианте.png")
    press(opt.locator("span[id]"))                     # текст варианта рядом с термином
    _closed(pg, tag, "выбор варианта")
    assert radio.get_attribute("aria-checked") == "true", f"{tag}: вариант не выбрался"
    press(opt.locator(".gl"))
    assert radio.get_attribute("aria-checked") == "true", f"{tag}: термин снял выбор радио"
    plain = pg.locator("#q-kind .opt").first          # вариант без термина — прежняя кнопка
    assert plain.get_attribute("role") == "radio" and plain.locator(".gl").count() == 0
    # флажок
    cb = pg.locator("#q-tags .opt").nth(1)
    box = cb.locator(".pick")
    assert box.get_attribute("role") == "checkbox"
    cb.scroll_into_view_if_needed()
    press(cb.locator(".gl").first)
    _tip_ok(pg, tag, "NFC")
    assert box.get_attribute("aria-checked") == "false", f"{tag}: термин отметил флажок"
    press(box)
    assert box.get_attribute("aria-checked") == "true", f"{tag}: флажок не отметился"
    press(cb.locator(".gl").first)
    assert box.get_attribute("aria-checked") == "true", f"{tag}: термин снял флажок"
    if shots:
        pg.screenshot(path=f"{shots}/{name}-3-термин-во-флажке.png")
    pg.keyboard.press("Escape")
    _closed(pg, tag, "Esc во флажке")


def run(url: str, shots: str = "", demo: bool = True):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    with sync_playwright() as p:
        for eng, w, theme in (("webkit", 390, "light"), ("chromium", 1366, "dark"), ("webkit", 390, "dark"),
                              ("chromium", 1366, "light")):
            phone, tag = w < 600, f"{eng}-{w}-{theme}"
            br = p.webkit.launch() if eng == "webkit" else p.chromium.launch(channel="chrome", headless=True)
            kw = {"viewport": {"width": w, "height": 844 if phone else 860}, "color_scheme": theme}
            if phone:
                kw |= {"is_mobile": True, "has_touch": True}
            ctx = br.new_context(**kw)
            pg = ctx.new_page()
            pg.on("console", lambda m, tag=tag: m.type == "error" and errs.append(f"{tag}: {m.text}"))
            pg.on("pageerror", lambda e, tag=tag: errs.append(f"{tag}: {e}"))
            pg.goto(url)
            check(pg, tag, phone, shots, f"{w}-{theme}-{eng}", demo)
            ctx.close()
            br.close()
    assert not errs, errs


def main():
    import os

    shots = sys.argv[1] if len(sys.argv) > 1 else ""
    form = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")) if len(sys.argv) > 2 else DEMO
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["GAS_PULT_DATA_DIR"] = tmp
        from gas_pult import webapp
        from gas_pult.config import Config

        panel = webapp.Panel(Config(token="1:T", owners=[1]))
        srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            if shots:
                Path(shots).mkdir(parents=True, exist_ok=True)
            run(f"http://127.0.0.1:{srv.server_address[1]}" + link(panel, form), shots, demo=form is DEMO)
        finally:
            srv.shutdown()
    print("ok")


if __name__ == "__main__":
    main()
