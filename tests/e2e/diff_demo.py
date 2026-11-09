"""Точечное обновление списка и ленты (план UX, пункт 1; Playwright; pytest запускает, только если есть браузер).

    python tests/e2e/diff_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Перерисовка без изменений не трогает DOM; новый ответ — один новый узел с анимацией появления, остальные сообщения —
те же узлы (прокрутка, раскрытые логи, выделение не сбиваются); изменившееся сообщение заменяется без анимации (.mupd).
Список сессий: опрос раз в 3 с не пересоздаёт карточки. 390 и 1366, светлая и тёмная; консоль без ошибок.
"""

import sys

WATCH = """(sel) => {                                     // считаем изменения DOM внутри sel
  window.__mut = 0;
  window.__mo?.disconnect();
  window.__mo = new MutationObserver((ms) => {
    for (const m of ms) {
      const t = m.target.nodeType === 1 ? m.target : m.target.parentElement;
      // «N назад» и таймер хода идут каждую секунду — это не перерисовка
      if (!t.closest(".ago, #act, #actx")) window.__mut += 1;
    }
  });
  const all = { subtree: true, childList: true, attributes: true, characterData: true };
  window.__mo.observe(document.querySelector(sel), all);
}"""


NEW_MSG = """() => {                                  // новый ответ агента
  const i = Math.max(...hist.map((m) => m.i)) + 1;
  const text = "Готово: **три** файла, [ссылка](https://example.com)";
  hist = [...hist, { role: "assistant", i, text, ts: Date.now() / 1000 }];
  window.NEW_SEL = () => `#content .msg[data-i='${i}']`;
  renderChat(false);
}"""
EDIT_MSG = """() => {                                 // агент дописал первый ответ
  const k = hist.findIndex((m) => m.role === "assistant");
  window.__ci = hist[k].i;
  hist = hist.map((m, j) => j === k ? { ...m, text: m.text + " (уточнено)" } : m);
  renderChat(false);
}"""


def run(base: str, shots: str | None = None):
    from playwright.sync_api import sync_playwright

    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for w in (390, 1366):
            for th in ("light", "dark"):
                pg = br.new_page(viewport={"width": w, "height": 860})
                pg.on("console", lambda m: m.type == "error" and "404" not in m.text and errs.append(m.text))
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.clock.install()
                pg.goto(f"{base}{sep}open=@1&theme={th}&noscroll")
                pg.clock.run_for(3000)
                pg.wait_for_selector("#content .msg")

                # 1. та же переписка — ни одного изменения в ленте
                pg.evaluate("() => { window.__old = [...document.querySelectorAll('#content .msg')]; }")
                # первое появление — уже позади
                pg.evaluate("() => __old.forEach((n) => n.getAnimations().forEach((a) => a.finish()))")
                pg.evaluate(WATCH, "#content")
                pg.evaluate("() => renderChat(false)")
                pg.evaluate("() => new Promise((r) => setTimeout(r, 0))")
                assert pg.evaluate("() => __mut") == 0, f"{w} {th}: перерисовка без изменений тронула ленту"

                # 2. новый ответ — один новый узел с анимацией, старые на месте
                pg.evaluate(NEW_MSG)
                ok = pg.evaluate("() => __old.every((n) => n.isConnected)")
                assert ok, f"{w} {th}: старые сообщения пересозданы"
                anim = pg.evaluate("() => getComputedStyle(document.querySelector(NEW_SEL())).animationName")
                assert anim != "none", f"{w} {th}: новое сообщение без анимации появления"
                olds = pg.evaluate("() => __old.filter((n) => n.getAnimations().length).length")
                assert olds == 0, f"{w} {th}: старые сообщения снова «появляются» ({olds})"
                link = pg.evaluate("() => !!document.querySelector(NEW_SEL() + \" a[href^='https://example.com']\")")
                assert link, "новое сообщение не дообработано (ссылка)"

                # 3. изменилось одно сообщение — заменён только он, без анимации
                pg.evaluate(EDIT_MSG)
                rep = pg.evaluate("() => __old.filter((n) => !n.isConnected).map((n) => +n.dataset.i)")
                assert rep == [pg.evaluate("() => __ci")], f"{w} {th}: заменены лишние сообщения: {rep}"
                upd = pg.evaluate("() => document.querySelector(`#content .msg[data-i='${__ci}']`).className")
                assert "mupd" in upd, \
                    "заменённое сообщение — без анимации (.mupd)"
                disp = pg.evaluate("() => getComputedStyle(document.querySelector(`#content .msg[data-i='${__ci}']`))"
                                   ".display")
                assert disp == "block", f"{w} {th}: заменённое сообщение получило чужие стили (display: {disp})"
                if shots:
                    pg.screenshot(path=f"{shots}/diff-chat-{w}-{th}.png")

                # 4. список сессий: опросы раз в 3 с не пересоздают карточки
                pg.evaluate("() => back()")
                pg.clock.run_for(3500)
                pg.evaluate("() => { window.__cards = [...document.querySelectorAll('#sessionsView .card')]; }")
                pg.evaluate(WATCH, "#sessionsView")
                pg.clock.run_for(30_000)
                n = pg.evaluate("() => __cards.length")
                kept = pg.evaluate("() => __cards.filter((c) => c.isConnected).length")
                assert n and kept == n, f"{w} {th}: карточки пересозданы ({kept} из {n})"
                mut = pg.evaluate("() => __mut")
                assert mut <= 2, f"{w} {th}: список менялся без изменений: {mut}"
                if shots:
                    pg.screenshot(path=f"{shots}/diff-list-{w}-{th}.png")
                pg.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs}"
    print("ok: точечное обновление")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8797/?demo", sys.argv[2] if len(sys.argv) > 2 else None)
