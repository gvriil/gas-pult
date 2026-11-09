"""Enter в поле ввода (задача 30; Playwright — pytest запускает, только если есть браузер).

    python tests/e2e/enter_demo.py http://127.0.0.1:8797/?demo

Компьютер (мышь, pointer: fine): Enter — отправить, Shift+Enter — новая строка, Ctrl/Cmd+Enter — отправить.
Телефон (is_mobile + touch, pointer: coarse): Enter — новая строка, Ctrl+Enter (внешняя клавиатура) — отправить,
enterkeyhint="enter". Во время IME-набора (isComposing) Enter не отправляет. Поле растёт до ~6 строк, дальше —
прокрутка внутри. Полный режим (``?demo&open=@1``) и простой (``&simple=1``). Консоль без ошибок.
"""

import sys

COMPOSING = """(sel) => {
  const t = document.querySelector(sel);
  t.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", isComposing: true, bubbles: true, cancelable: true }));
  t.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 229, bubbles: true, cancelable: true }));
}"""

# высота поля меняется раз за кадр (fitLines, план UX, пункт 8) — после каждого ввода ждём кадр
GROW = """async (sel) => {
  const t = document.querySelector(sel), lh = parseFloat(getComputedStyle(t).lineHeight);
  const frame = () => new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(ok)));
  const set = async (n) => { t.value = Array.from({ length: n }, (_, i) => "строка " + (i + 1)).join("\\n");
    t.dispatchEvent(new Event("input", { bubbles: true })); await frame(); return t.getBoundingClientRect().height; };
  const one = await set(1), three = await set(3), ten = await set(10), over = getComputedStyle(t).overflowY;
  t.value = ""; t.dispatchEvent(new Event("input", { bubbles: true }));
  return { lh, one, three, ten, over };
}"""


def run(base: str):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for mode, q, sel in (("full", "open=@1", "#input"), ("simple", "simple=1", "#sInput")):
            for dev in ("pc", "phone"):
                where = f"{mode} {dev}"
                kw = {"viewport": {"width": 1366, "height": 860}} if dev == "pc" else \
                    {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
                ctx = br.new_context(**kw)
                pg = ctx.new_page()
                pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(f"{base}{sep}{q}")
                pg.wait_for_selector(sel + ":visible", timeout=8000)
                assert pg.get_attribute(sel, "enterkeyhint") == "enter", where
                touch = pg.evaluate("touchInput()")
                assert touch == (dev == "phone"), f"{where}: touchInput() = {touch}"

                def sent(text: str, key: str, pg=pg, sel=sel) -> bool:
                    pg.fill(sel, text)
                    pg.focus(sel)
                    pg.keyboard.press(key)
                    pg.wait_for_timeout(250)
                    return pg.input_value(sel) == ""

                if dev == "pc":
                    assert sent("первое", "Enter"), f"{where}: Enter не отправил"
                    assert not sent("строка", "Shift+Enter"), f"{where}: Shift+Enter отправил"
                    assert pg.input_value(sel) == "строка\n", f"{where}: Shift+Enter — не новая строка"
                else:
                    assert not sent("строка", "Enter"), f"{where}: Enter экранной клавиатуры отправил"
                    assert pg.input_value(sel) == "строка\n", f"{where}: Enter — не новая строка"
                assert sent("через ctrl", "Control+Enter"), f"{where}: Ctrl+Enter не отправил"
                assert sent("через cmd", "Meta+Enter"), f"{where}: Cmd+Enter не отправил"
                pg.fill(sel, "набор")
                pg.evaluate(COMPOSING, sel)
                pg.wait_for_timeout(200)
                assert pg.input_value(sel) == "набор", f"{where}: Enter во время IME-набора отправил"
                g = pg.evaluate(GROW, sel)
                assert g["three"] > g["one"] + g["lh"] * 1.5, f"{where}: поле не растёт {g}"
                assert g["lh"] * 5.5 < g["ten"] < g["lh"] * 7.5, f"{where}: 10 строк — не ~6 строк высотой {g}"
                assert g["over"] == "auto", f"{where}: больше 6 строк — нет прокрутки {g}"
                ctx.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs[:5]}"


if __name__ == "__main__":
    run(sys.argv[1])
    print("ok")
