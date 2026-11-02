"""Проверка простого режима в демо панели (Playwright; pytest её не запускает — нужен браузер).

    python tests/e2e/simple_mode.py http://127.0.0.1:8797/?demo [папка-для-скриншотов]

``?demo&simple=1`` (русский) и ``&lang=en``: телефон 390, планшет 820, ПК 1366, светлая и тёмная тема. На экране
(видимый текст, подсказки полей и подписи кнопок) — ни одной латинской буквы в русском, кроме имён собственных из
``humanize.LATIN_OK``, и ни одной кириллической в английском, кроме ``humanize.CYRILLIC_OK``. Вопрос разрешения
«Do you want to proceed?» — русскими (английскими) чипами; нажатие «Да» отвечает агенту; листы «Мои агенты»,
«Настройки», «Подробности», «Подключить агента» и помощник — тоже без чужих букв. Первый экран ``view=login&lang=en``
— по-английски. Полный режим ``?demo`` — прежний: простого экрана нет. Консоль без ошибок.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from gas_pult.humanize import CYRILLIC_OK, LATIN_OK

LATIN, CYRILLIC = re.compile(r"[A-Za-z]"), re.compile(r"[А-Яа-яЁё]")

# Весь видимый текст: innerText простого экрана и открытых листов, всплывающие сообщения, подсказки полей и подписи
# кнопок (их читает экранный диктор).
VISIBLE = """() => {
  const roots = [...document.querySelectorAll('#simple:not([hidden]), .sheet-bg, .toast')];
  const out = roots.map((r) => r.innerText);
  for (const r of roots) for (const el of r.querySelectorAll('[placeholder], [aria-label]')) {
    if (el.offsetParent === null) continue;
    out.push(el.getAttribute('placeholder') || '', el.getAttribute('aria-label') || '');
  }
  return out.join('\\n');
}"""


def strangers(text: str, lang: str) -> list[str]:
    """Чужие буквы на экране: в русском — латиница вне белого списка, в английском — кириллица вне своего."""
    for w in sorted(LATIN_OK if lang == "ru" else CYRILLIC_OK, key=len, reverse=True):
        text = re.sub(rf"(?<![A-Za-zА-Яа-яЁё]){re.escape(w)}(?![A-Za-zА-Яа-яЁё])", " ", text)
    rx = LATIN if lang == "ru" else CYRILLIC
    return sorted({m.group(0) for m in re.finditer(r"\S*" + rx.pattern + r"\S*", text)})


def check(pg, lang: str, where: str):
    bad = strangers(pg.evaluate(VISIBLE), lang)
    assert not bad, f"{where}: чужие буквы на экране ({lang}): {bad[:12]}"


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for w in (390, 820, 1366):
            for theme in ("light", "dark"):
                for lang in ("ru", "en"):
                    pg = br.new_page(viewport={"width": w, "height": 820})
                    pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                    pg.on("pageerror", lambda e: errs.append(str(e)))
                    tag = f"{w}-{theme}-{lang}"
                    pg.goto(f"{base}{sep}simple=1&lang={lang}&theme={theme}")
                    pg.wait_for_function("typeof start === 'function' && start.done")
                    pg.wait_for_selector("#sAsk .scn-opt", timeout=8000)
                    pg.wait_for_timeout(600)
                    assert pg.is_visible("#simple") and not pg.is_visible("#top"), f"{tag}: не простой экран"
                    col = pg.locator("#sFeed").bounding_box()
                    assert col["width"] <= 760 and (w < 800 or abs(col["x"] + col["width"] / 2 - w / 2) < 20), \
                        f"{tag}: разговор не по центру: {col}"
                    want = {"ru": "Агент хочет выполнить действие на компьютере",
                            "en": "The agent wants to run an action on the computer"}[lang]
                    assert want in pg.inner_text("#sAsk"), f"{tag}: нет перевода вопроса"
                    check(pg, lang, tag)
                    if shots:
                        pg.screenshot(path=f"{shots}/simple-{tag}.png")
                    # опасные пункты — вторым уровнем, с пояснением
                    pg.click("#sAsk [data-smore]")
                    pg.wait_for_selector("#sAsk .s-two")
                    check(pg, lang, tag + " другие варианты")
                    if shots and theme == "light":
                        pg.screenshot(path=f"{shots}/simple-{tag}-more.png")
                    # подробности, мои агенты, настройки, новый агент, помощник — без чужих букв
                    more = "Показать подробности" if lang == "ru" else "Show details"
                    pg.click(f'#sAsk [data-sopt]:has-text("{more}")')
                    pg.wait_for_selector(".sheet-bg .s-sheet")
                    assert pg.evaluate("helpContext().screen") == "simple.details"
                    check(pg, lang, tag + " подробности")
                    pg.click(".sheet-bg [data-close]")
                    for btn, screen in (("#sWho", "simple.agents"), ("#sSet", "simple.settings")):
                        pg.click(btn)
                        pg.wait_for_selector(".sheet-bg .s-sheet")
                        assert pg.evaluate("helpContext().screen") == screen, screen
                        pg.wait_for_timeout(200)
                        check(pg, lang, f"{tag} {screen}")
                        if shots and w == 390 and theme == "light":
                            pg.screenshot(path=f"{shots}/simple-{tag}-{screen.split('.')[1]}.png")
                        pg.click(".sheet-bg [data-close]")
                    pg.evaluate("sNewAgent()")
                    pg.wait_for_selector(".sheet-bg .s-sheet")
                    if lang == "ru":
                        pg.click(".sheet-bg [data-ind]")
                        pg.click(".sheet-bg [data-mod]")
                    check(pg, lang, tag + " новый агент")
                    pg.click(".sheet-bg [data-close]")
                    pg.click("#sHelp")
                    pg.wait_for_selector(".help-bg .ha:not(.wait)")
                    pg.click(".help-bg .hchips button")
                    pg.wait_for_timeout(300)
                    check(pg, lang, tag + " помощник")
                    pg.click(".help-bg [data-close]")
                    # «Да» — ответ уходит, вопрос исчезает, строка статуса — общими словами
                    pg.click('#sAsk [data-sopt]:has-text("%s")' % ("Да" if lang == "ru" else "Yes"))
                    pg.wait_for_function("!document.querySelector('#sAsk .s-ask')", timeout=5000)
                    pg.wait_for_timeout(2000)
                    check(pg, lang, tag + " после ответа")
                    st = pg.inner_text("#sAct")
                    assert st.startswith("Выполняет действие" if lang == "ru" else "Running an action"), st
                    # сообщение агенту
                    pg.fill("#sInput", "Проверь отзывы" if lang == "ru" else "Check the reviews")
                    pg.click("#sSend")
                    pg.wait_for_timeout(1200)
                    check(pg, lang, tag + " после отправки")
                    pg.close()
        # первый экран: переключатель языка и английский
        for w in (390, 1366):
            pg = br.new_page(viewport={"width": w, "height": 820})
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"{base}{sep}view=login&lang=en")
            pg.wait_for_selector("#loginLang .scn-opt.on")
            pg.wait_for_timeout(400)
            txt = pg.evaluate("[...document.querySelectorAll('#top, #login, #demoBar')]"
                              ".map((x) => x.innerText).join('\\n')")
            bad = strangers(txt, "en")
            assert not bad and "Sign in with Telegram" in txt, f"вход {w}px: {bad}"
            if shots:
                pg.screenshot(path=f"{shots}/login-en-{w}.png")
            pg.click('#loginLang [data-lang="ru"]')
            pg.wait_for_timeout(500)
            assert "Войти через Telegram" in pg.inner_text("#login")
            pg.close()
        # полный режим — прежний: простого экрана нет, список сессий на месте
        pg = br.new_page(viewport={"width": 1366, "height": 820})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{base}{sep}home=1")
        pg.wait_for_function("typeof start === 'function' && start.done")
        pg.wait_for_timeout(500)
        assert not pg.is_visible("#simple") and pg.is_visible("#sessionsView"), "полный режим изменился"
        if shots:
            pg.screenshot(path=f"{shots}/full-1366.png")
        pg.close()
        br.close()
    assert not errs, errs
    print("простой режим: ок")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
