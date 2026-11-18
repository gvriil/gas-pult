"""GAS-21 (Алексей: «сообщение не отправилось и дальше остаётся неотправленным, что бы ни происходило»; Playwright).

    python tests/e2e/unsent_demo.py http://127.0.0.1:8797/?demo

  (а) отказ сервера — «не отправлено» с «Отправить ещё раз» и «Удалить»; «Удалить» убирает строку;
  (б) «Отправить ещё раз» — уходит, строка «доставлено»;
  (в) обрыв связи — «нет связи»; связь вернулась (событие online) — пульт повторяет сам;
  (г) неотправленное другой сессии в этом чате не показывается. 390 px; консоль без ошибок.
"""

import sys

FAIL = """() => { window.__api = window.__api || api; window.__mode = 'fail';
  window.api = async (path, body) => {
    if (path === '/api/send' && window.__mode === 'fail') { const e = new Error('окно занято'); throw e; }
    if (path === '/api/send' && window.__mode === 'net') { const e = new Error('нет сети'); e.net = true; throw e; }
    return window.__api(path, body); }; }"""


def run(base: str):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 844})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.clock.install()
        pg.goto(base)
        pg.clock.run_for(3000)
        sid = pg.evaluate("sessions.find((s) => s.status !== 'stopped').id")
        pg.evaluate(f"openSession({sid!r})")
        pg.clock.run_for(1500)
        pg.evaluate(FAIL)

        def send(t):
            pg.fill("#input", t)
            pg.evaluate("sendText()")
            pg.clock.run_for(500)

        send("Проверь отчёт за ноябрь")                                         # (а)
        st = pg.locator("#content .msg.me .state.bad").last
        assert "не отправлено" in st.inner_text() and st.locator("[data-unsend]").count() == 1, st.inner_text()
        st.locator("[data-unsend]").click()
        pg.clock.run_for(300)
        assert pg.locator("#content .msg.me .state.bad").count() == 0, "«Удалить» не убрал строку"
        send("Посчитай остатки на складе")                                       # (б)
        pg.evaluate("window.__mode = 'ok'")
        pg.locator("#content .msg.me .state.bad [data-resend]").last.click()
        pg.clock.run_for(800)
        assert pg.locator("#content .msg.me .state.bad").count() == 0, "«Отправить ещё раз» не отправил"
        assert "доставлено" in pg.locator("#content .msg.me .state").last.inner_text()
        pg.evaluate("window.__mode = 'net'")                                      # (в)
        send("Сверь платежи за неделю")
        pg.clock.run_for(15000)
        assert "нет связи" in pg.locator("#content .msg.me .state.bad").last.inner_text()
        pg.evaluate("window.__mode = 'ok'; dispatchEvent(new Event('online'))")
        pg.clock.run_for(800)
        assert pg.locator("#content .msg.me .state.bad").count() == 0, "после возврата связи не повторил"
        pg.evaluate("window.__mode = 'fail'")                                     # (г)
        send("Только для этой сессии")
        other = pg.evaluate(f"sessions.find((s) => s.id !== {sid!r} && s.status !== 'stopped').id")
        pg.evaluate(f"openSession({other!r})")
        pg.clock.run_for(1500)
        assert "Только для этой сессии" not in pg.inner_text("#content"), "неотправленное видно в чужом чате"
        b.close()
    assert not errs, errs


if __name__ == "__main__":
    run(sys.argv[1])
    print("ok")
