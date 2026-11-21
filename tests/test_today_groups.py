"""«Сегодня» с первого взгляда (владелец 21.11; ориентиры — Things 3 «Today», Linear Inbox, «Напоминания»): итог
одной строкой, затем группы «Ждут вашего Да» → «Сегодня» → «Сделано» (свёрнуто, со счётчиком) → «Не выполнено».
Пустая группа не показывается, кроме «Ждут вашего Да» — там одна строка «Решений от вас не ждут». «Да» по-прежнему
просит подтверждения, строки разработки скрыты у пользователя. Разметку проверяем в браузере демо, если есть
Playwright; иначе — только статически."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
JS = (WEB / "js" / "brief.js").read_text(encoding="utf-8")


def test_groups_order_in_markup():
    i = [JS.index(f'data-group="{g}"') for g in ("decisions", "today", "done", "failed")]
    assert i == sorted(i) and JS.index('data-tour="brief-head"') < i[0]
    assert '<details class="fold" data-tour="brief-done">' in JS                  # «Сделано» — свёрнуто (без open)
    assert "Решений от вас не ждут</div>" in JS and "Ждут вашего Да" in JS
    for n in ("nt", "ndone", "nf"):                                               # пустые — не показываем
        assert "${" + n + " ? `<section" in JS


def test_typography_and_targets():
    assert "margin: 0 0 6px; font-size: 15px; font-weight: 600;" in JS            # заголовки групп 15/600
    assert "font-size: 15px; line-height: 22px;" in JS and ".brief .bl { margin: 10px 0 6px; font-size: 18px;" in JS
    assert "-webkit-line-clamp: 2" in JS and "text-overflow: ellipsis" in JS     # длинное — «…», раскрытие нажатием
    assert ".brief .acts .btn { min-height: 44px; }" in JS                       # телефон — цели 44 px
    assert ".brief { max-width: 780px;" in JS                                     # колонка — как абзацы ленты


@pytest.fixture(scope="module")
def page():
    sync = pytest.importorskip("playwright.sync_api")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(WEB)))
    srv.RequestHandlerClass.log_message = lambda *a: None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:                                                   # нет браузера Playwright
            srv.shutdown()
            pytest.skip(f"нет Chromium для Playwright: {e}")
        pg = b.new_page(viewport={"width": 390, "height": 844})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/?demo&theme=light")
        pg.wait_for_function("typeof part === 'function'")
        pg.wait_for_timeout(800)
        yield pg, errs
        b.close()
    srv.shutdown()


def _open(pg, brief=None):
    """Открыть «Сегодня»; ``brief`` — подменить ответ /api/brief (поля сервера — как в brief.assemble)."""
    if brief is not None:
        pg.evaluate("""(b) => { window.__api ||= window.api;
          window.api = (p, body) => p.split("?")[0] !== "/api/brief" ? window.__api(p, body)
            : window.__api(p, body).then((d) => ({ ...d, brief: { ...d.brief, ...b } })); }""", brief)
    pg.evaluate('part("brief").then((m) => m.briefOpen("fresh"))')
    pg.wait_for_selector(".brief .bl")
    return pg.evaluate("""() => [...document.querySelectorAll(".brief-bg [data-group]")].map((s) => s.dataset.group)""")


def test_order_and_done_folded(page):
    pg, errs = page
    assert _open(pg) == ["decisions", "today", "done", "failed"]
    assert pg.evaluate('document.querySelector("[data-tour=brief-done]").open') is False
    assert pg.locator(".brief [data-group=done] h3").inner_text().split() == ["Сделано", "2"]
    assert not pg.locator(".brief [data-group=done] li").first.is_visible()
    pg.click(".brief [data-group=done] summary")
    assert pg.locator(".brief [data-group=done] li").first.is_visible()
    assert pg.locator(".brief [data-group=today] .tm").first.inner_text().startswith("10:00")    # время — слева
    for t in ("brief-head", "brief-decisions", "brief-today", "brief-done", "brief-prefs"):        # якоря тура
        assert pg.locator(f'[data-tour="{t}"]').count() == 1, t
    box = pg.locator('.brief .dec [data-a="yes"]').first.bounding_box()
    assert box["height"] >= 44 and box["width"] < 200                                          # компактная, 44 px
    assert errs == []


def test_empty_groups_hidden_decisions_one_line(page):
    pg, errs = page
    got = _open(pg, {"decisions": [], "today": [], "done": [], "failed": [], "more": {},
                     "headline": "Решений от вас не ждут. Ночью срочного не было."})
    assert got == ["decisions"]
    assert pg.locator(".brief [data-group=decisions]").inner_text().strip() == "Решений от вас не ждут"
    assert pg.locator(".brief .bl").inner_text().strip() == "Ночью срочного не было."             # без повтора
    assert errs == []


def test_yes_asks_and_chat_opens_new_chat(page):
    pg, _ = page
    pg.evaluate("window.__api && (window.api = window.__api); delete window.demoApi.brief")
    _open(pg)
    asked = []
    pg.once("dialog", lambda d: (asked.append(d.message), d.dismiss()))
    pg.click('.brief .dec:nth-of-type(2) [data-a="yes"]')                         # PR — слияние после подтверждения
    pg.wait_for_timeout(300)
    assert asked and "shop/site#42" in asked[0]                                   # спросили «Слить …?», отказались
    assert pg.locator(".brief .dec").count() == 3                                 # без подтверждения ничего не ушло
    pg.keyboard.press("Escape")
    _open(pg)
    pg.click('.brief .dec:nth-of-type(1) [data-a="chat"]')                        # «В чат» — новый чат, пункт в поле
    pg.wait_for_function('document.getElementById("input")?.value.includes("Ромашка")')
    assert pg.locator(".brief-bg").count() == 0
