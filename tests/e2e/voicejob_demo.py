"""GAS-34 (Playwright): длинная запись — фоновое задание без лимита 90 с; сбой — запись не теряется.

    python tests/e2e/voicejob_demo.py http://127.0.0.1:8797/?demo

  (а) запись → «Распознаю…» → текст в поле, в IndexedDB ничего не осталось;
  (б) ?stt=fail — ошибка с «Повторить» и «Скачать», запись — в IndexedDB; перезагрузка → «Есть нераспознанная запись»;
  (в) распознать её оттуда → текст в поле. 390 px; консоль без ошибок.
"""

import sys

import _onebrowser  # noqa: F401  — e2e с браузером по одному на сервер (tests/heavy_lock.py)

COUNT = """() => new Promise((ok) => { const r = indexedDB.open("gas-pult", 1);
  r.onupgradeneeded = () => r.result.createObjectStore("voice");
  r.onsuccess = () => { const q = r.result.transaction("voice").objectStore("voice").count();
    q.onsuccess = () => ok(q.result); }; })"""
REC = "sttRun(new Blob([new Uint8Array(64000)], { type: 'audio/webm' }), false)"


def run(base: str):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 844})
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base)
        pg.wait_for_timeout(2500)
        pg.evaluate("openSession(sessions.find((s) => s.status !== 'stopped').id)")
        pg.wait_for_timeout(1000)
        pg.evaluate(REC)                                                         # (а)
        pg.wait_for_function("document.getElementById('input').value.includes('изменилось')", timeout=15000)
        assert pg.evaluate(COUNT) == 0, "после распознавания запись осталась в браузере"
        pg.goto(base + "&stt=fail")                                              # (б)
        pg.wait_for_timeout(2500)
        pg.evaluate("openSession(sessions.find((s) => s.status !== 'stopped').id)")
        pg.wait_for_timeout(1000)
        pg.evaluate(REC)
        pg.wait_for_selector(".recbar.err", timeout=15000)
        bar = pg.inner_text(".recbar.err")
        assert "Повторить" in bar and "Скачать" in bar, bar
        assert pg.evaluate(COUNT) == 1, "запись не сохранилась в браузере"
        pg.evaluate("$('input').value = ''; sessionStorage.clear()")            # черновик поля не мешает проверке
        pg.goto(base)                                                            # (в) перезагрузка — запись ждёт
        pg.wait_for_selector("text=Есть нераспознанная запись", timeout=10000)
        pg.locator(".sheet button", has_text="распознать").first.click()
        pg.wait_for_function("document.getElementById('input').value.includes('изменилось')", timeout=15000)
        for _ in range(30):
            if pg.evaluate(COUNT) == 0:
                break
            pg.wait_for_timeout(200)
        assert pg.evaluate(COUNT) == 0, "распознанная запись осталась в браузере"
        b.close()
    assert not errs, errs


if __name__ == "__main__":
    run(sys.argv[1])
    print("ok")
