"""«Изменена N назад» в браузере: agoText/agoExact из index.html дают то же, что ago.py (Playwright; pytest
запускает, если есть Playwright и Chrome — tests/test_ago.py).

    python tests/e2e/ago_check.py http://127.0.0.1:8797/?demo

Страница открывается в часовом поясе ``TZ`` (как у процесса Python), язык — ru и en. Отдельно — демо 390 и 1366 px:
на карточках и в шапке есть отметка времени, текст обновляется на месте (тот же узел), консоль без ошибок.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from gas_pult import ago

NOW = 1793779200.0                         # 2026-11-04 08:00:00 UTC
SECS = [0, 3, 4, 5, 6, 30, 59, 60, 61, 119, 120, 300, 659, 660, 1260, 3599, 3600, 7199, 7200, 18000, 75600, 86399,
        86400, 100000, 172799, 172800, 259200, 604799, 604800, 1209600, 1814400, 2591999, 2592000, 5184000,
        13000000, 31535999, 31536000, 40000000, -30]


def cases() -> list[tuple[float, float, bool]]:
    out = [(NOW - s, NOW, full) for s in SECS for full in (False, True)]
    out += [(NOW - 400 * 86400, NOW, False), (1767225599.0, 1767225601.0, False)]   # дата; переход года
    return out


def expected(lang: str) -> list[list[str]]:
    return [[ago.ago(ts, now, lang, full), ago.exact(ts, now, lang)] for ts, now, full in cases()]


JS = """async ([lang, cases]) => {
  LANG = lang; await loadDict(lang);
  return cases.map(([ts, now, full]) => [agoText(ts, now, full), agoExact(ts, now)]);
}"""


def compare(pg) -> None:
    for lang in ("ru", "en"):
        got = pg.evaluate(JS, [lang, cases()])
        want = expected(lang)
        bad = [(c, g, w) for c, g, w in zip(cases(), got, want, strict=True) if g != w]
        assert not bad, f"{lang}: JS и Python расходятся: {bad[:5]}"


def run(base: str, shots: str = "") -> None:
    from playwright.sync_api import sync_playwright

    tz = os.environ.get("TZ") or "UTC"
    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        ctx = br.new_context(timezone_id=tz, viewport={"width": 390, "height": 800})
        pg = ctx.new_page()
        pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"{base}{sep}home=1")
        pg.wait_for_selector(".card .ago")
        compare(pg)
        for w in (390, 1366):
            for theme in ("light", "dark"):
                pg = ctx.new_page()
                pg.set_viewport_size({"width": w, "height": 800})
                pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.goto(f"{base}{sep}theme={theme}&home=1")
                pg.wait_for_selector(".card .ago")
                q = ".card[data-id='@1'] .ago"
                first = pg.locator(q)
                assert "с назад" in first.inner_text(), first.inner_text()     # меньше минуты — секунды
                pg.evaluate(f"document.querySelector(`{q}`).dataset.mark = '1'")
                before = first.inner_text()
                time.sleep(2.2)
                assert pg.evaluate(f"document.querySelector(`{q}`).dataset.mark") == "1"   # тот же узел
                assert first.inner_text() != before                               # обновился раз в секунду
                assert pg.locator(".card.stale").count() == 1 and pg.locator(".chip.stale").count() == 1
                order = pg.eval_on_selector_all(".card[data-id]", "els => els.map((e) => e.dataset.id)")
                assert order == ["@2", "@1", "@3", "@4", "@5"], order               # ждущая — сверху, дальше по времени
                if shots:
                    pg.screenshot(path=f"{shots}/ago-list-{w}-{theme}.png")
                pg.locator(".card[data-id='@2'] .name").click()
                where = "#subtitle .ago" if w > 1000 else "#target .ago"         # телефон — строка «куда пишете»
                pg.wait_for_selector(where)
                head = pg.inner_text(where)
                want = "изменена 4 минуты назад · ваше сообщение — 25 минут назад" if w > 1000 else "4 мин"
                assert head == want, head
                if shots:
                    pg.screenshot(path=f"{shots}/ago-head-{w}-{theme}.png")
                pg.close()
        br.close()
    assert not errs, errs


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    print("ok")
