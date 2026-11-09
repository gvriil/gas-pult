"""Опрос только для зрителя (Playwright с подменой часов; pytest запускает, только если есть браузер).

    python tests/e2e/viewer_poll.py http://127.0.0.1:8797/?demo

Панель открыта и её касаются — список сессий раз в 3 с. Вкладка скрыта — ни одного опроса (каждый опрос на сервере —
список окон tmux, у демо-пространств ещё и sudo). 10 минут без касаний — раз в 30 с, без плашки «нет связи». Касание —
сразу свежий список и обычный темп. Консоль без ошибок.
"""

import sys

COUNT = """() => {                                  // считаем запросы, не меняя ответов демо
  window.__calls = [];
  const orig = demoApi;
  demoApi = (path, body) => { window.__calls.push(path.split("?")[0]); return orig(path, body); };
}"""
HIDE = """(on) => {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => on });
  document.dispatchEvent(new Event("visibilitychange"));
}"""


def run(base: str):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        pg = br.new_page(viewport={"width": 390, "height": 844})
        pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.clock.install()
        pg.goto(f"{base}{sep}theme=light&noscroll")
        pg.clock.run_for(3000)
        pg.evaluate("() => { try { localStorage.setItem('gp:tourDone', '1'); } catch (e) {} }")
        pg.evaluate(COUNT)

        def polls(ms: int) -> int:
            pg.evaluate("() => { window.__calls = []; }")
            pg.clock.run_for(ms)
            return sum(1 for c in pg.evaluate("() => window.__calls") if c in ("/api/sessions", "/api/projects"))

        pg.mouse.move(10, 10)
        pg.mouse.down()
        pg.mouse.up()
        seen = polls(30_000)
        assert seen >= 8, f"зритель есть — опрос раз в 3 с, а было {seen} за 30 с"

        pg.evaluate(HIDE, True)
        assert polls(120_000) == 0, "вкладка скрыта — опроса быть не должно"
        pg.evaluate("() => { window.__calls = []; }")
        pg.evaluate(HIDE, False)
        pg.clock.run_for(100)
        assert "/api/sessions" in pg.evaluate("() => window.__calls") or \
            "/api/projects" in pg.evaluate("() => window.__calls"), "вкладку открыли — список сразу"

        pg.clock.run_for(11 * 60_000)                     # 11 минут без касаний
        slow = polls(120_000)
        assert 2 <= slow <= 5, f"без касаний — раз в 30 с, а было {slow} за 2 минуты"
        assert pg.evaluate("() => document.getElementById('net').hidden"), "редкий опрос — не «нет связи»"

        pg.evaluate("() => { window.__calls = []; }")
        pg.mouse.down()
        pg.mouse.up()
        pg.clock.run_for(100)
        assert pg.evaluate("() => window.__calls").count("/api/sessions") + \
            pg.evaluate("() => window.__calls").count("/api/projects") >= 1, "касание — список сразу"
        assert polls(30_000) >= 8, "после касания — снова раз в 3 с"
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: опрос только для зрителя")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo")
