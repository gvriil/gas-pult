"""«Проекты» (задача 49, PR 3; Playwright).

    python tests/e2e/projects_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Главная «Проекты»: карточки проектов (ждущий ответа — сверху), поиск, переключатель на прежние «Сессии»; проект —
активные чаты окнами и «Завершённые» (журналы без окна) с честной строкой о сроке хранения; переписка завершённого
чата без окна и «Продолжить этот чат»; «Новая сессия в проекте» внизу; «‹ Назад» ведёт в список проектов.
Ширина 390 и 1366, светлая и тёмная тема, консоль без ошибок.
"""

import sys


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for dev, theme in (("phone", "light"), ("pc", "dark"), ("phone", "dark"), ("pc", "light")):
            kw = {"viewport": {"width": 1366, "height": 860}} if dev == "pc" else \
                {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
            ctx = br.new_context(**kw)
            pg = ctx.new_page()
            pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"{base}{sep}home&proj&theme={theme}&noscroll")
            pg.wait_for_selector("#projectsView .card[data-proj]", timeout=5000)
            assert pg.is_visible("#projectsView") and not pg.is_visible("#sessionsView"), "главная — не «Проекты»"
            first = pg.eval_on_selector_all("#projectsView .card[data-proj]", "els => els.map((e) => e.dataset.proj)")
            assert first[0] == "p-icon", first                         # ждущий ответа — сверху
            assert pg.is_visible("#projSegBtn") and pg.locator("#homeSeg button.on").inner_text() == "Проекты"
            if shots:
                pg.screenshot(path=f"{shots}/projects-{dev}-{theme}.png")
            pg.fill("#projQ", "бухг")
            pg.wait_for_timeout(200)
            assert pg.eval_on_selector_all("#projectsView .card[data-proj]", "els => els.length") == 1
            pg.fill("#projQ", "")
            pg.click("#homeSeg button[data-v=sessions]")                 # прежний список окон — как был
            pg.wait_for_selector("#sessionsView .card[data-id]", timeout=4000)
            assert not pg.is_visible("#projectsView")
            pg.click("#homeSeg button[data-v=projects]")
            pg.wait_for_selector("#projectsView .card[data-proj]", timeout=4000)
            pg.click("#projectsView .card[data-proj='p-tgi']")
            pg.wait_for_selector("#projSeg", timeout=4000)
            pg.wait_for_selector("#projChats .card[data-id='@1']", timeout=4000)   # активный чат — окно проекта
            assert "Новая сессия в проекте" in pg.inner_text("#newBtn")
            if shots:
                pg.screenshot(path=f"{shots}/project-{dev}-{theme}.png")
            pg.click("#projSeg button[data-pt=done]")
            pg.wait_for_selector("#projChats .card[data-chat]", timeout=4000)
            assert "удаляет сам" in pg.inner_text("#projChats")             # честно о сроке хранения
            assert pg.locator("#projChats [data-resume]").count() == 2      # третий чат — другой учётки
            pg.click("#projChats .card[data-chat] .name >> nth=0")
            pg.wait_for_selector(".chatv .bubble", timeout=4000)
            assert pg.is_visible(".chatv [data-go-resume]")
            pg.wait_for_timeout(400)                                     # лист выезжает 0,2 с
            if shots:
                pg.screenshot(path=f"{shots}/project-chat-{dev}-{theme}.png")
            pg.click(".chatv [data-close]")
            if dev == "phone":
                pg.click("#backBtn")                                     # «‹ Назад» — к списку проектов
            else:
                pg.click("[data-pback]")
            pg.wait_for_selector("#projQ", timeout=4000)
            assert pg.is_visible("#projectsView .card[data-proj]")
            ctx.close()
        br.close()
    assert not errs, errs
    print("проекты: ок (390/1366, светлая/тёмная)")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
