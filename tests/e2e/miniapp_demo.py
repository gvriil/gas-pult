"""Панель как Mini App внутри Telegram — эмуляция Telegram.WebApp в демо (Playwright).

    python tests/e2e/miniapp_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Скрипт telegram.org подменяется заглушкой с непустым initData (как у кнопки «Панель» в боте) и записью вызовов.
Телефон 390 (Android) и компьютер 1366 (Telegram Desktop), тема из ``colorScheme`` — светлая и тёмная:
  - при запуске вызваны ready, expand, disableVerticalSwipes, BackButton.onClick, подписка на themeChanged и
    viewportChanged; цвет шапки и фона Telegram — из токена ``--bg-canvas``; тема страницы — из colorScheme;
  - телефон: панель сама открывает сессию, кнопка Telegram «Назад» видна; её нажатие — на главную, кнопка скрыта;
  - компьютер: главная со списком, «Назад» скрыта;
  - внешняя ссылка — через openLink (новой вкладки нет), подтверждение опасного — окном Telegram (showConfirm);
  - без горизонтальной прокрутки, консоль без ошибок.
Эталон для разбиения пульта на модули: тот же прогон до и после каждого переноса.
"""

import sys
from pathlib import Path

STUB = """(() => {
  const T = window.__tg = { calls: [], events: [], colors: [], opened: [], confirms: [], back: null };
  const rec = (n) => () => { T.calls.push(n); };
  const BB = { isVisible: false, show() { this.isVisible = true; T.calls.push("BackButton.show"); },
               hide() { this.isVisible = false; T.calls.push("BackButton.hide"); },
               onClick(f) { T.back = f; T.calls.push("BackButton.onClick"); }, offClick() {} };
  window.Telegram = { WebApp: {
    initData: "query_id=demo&user=%7B%22id%22%3A1%7D&auth_date=1&hash=demo", initDataUnsafe: { user: { id: 1 } },
    platform: "PLATFORM", version: "8.0", colorScheme: "SCHEME", themeParams: {}, isExpanded: true,
    viewportHeight: innerHeight, viewportStableHeight: innerHeight,
    ready: rec("ready"), expand: rec("expand"), disableVerticalSwipes: rec("disableVerticalSwipes"),
    onEvent: (e) => T.events.push(e), offEvent() {},
    setHeaderColor: (c) => T.colors.push(["header", c]), setBackgroundColor: (c) => T.colors.push(["bg", c]),
    setBottomBarColor: (c) => T.colors.push(["bottom", c]),
    openLink: (u) => T.opened.push(u), openTelegramLink: (u) => T.opened.push(u),
    showConfirm: (t, cb) => { T.confirms.push(t); cb(false); },
    BackButton: BB,
    HapticFeedback: { impactOccurred: rec("haptic"), notificationOccurred: rec("haptic"),
                      selectionChanged: rec("haptic") },
  } };
})();"""


def fake(body: str):
    """Обработчик подмены скрипта Telegram (один аргумент: Playwright передаёт и request, если их два)."""
    return lambda route: route.fulfill(body=body, content_type="text/javascript")


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    out = Path(shots) if shots else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for w, plat in ((390, "android"), (1366, "tdesktop")):
            for scheme in ("light", "dark"):
                tag = f"{w} {scheme}"
                mobile = w < 600
                ctx = br.new_context(viewport={"width": w, "height": 844 if mobile else 860}, is_mobile=mobile,
                                     has_touch=mobile)
                stub = STUB.replace("PLATFORM", plat).replace("SCHEME", scheme)
                ctx.route("https://telegram.org/js/telegram-web-app.js", fake(stub))
                pg = ctx.new_page()
                pg.on("console", lambda m, t=tag: m.type == "error" and "Failed to load resource" not in m.text
                      and errs.append(f"{t}: {m.text}"))
                pg.on("pageerror", lambda e, t=tag: errs.append(f"{t}: {e}"))
                pg.goto(f"{base}{sep}noscroll")
                pg.wait_for_selector("#content .msg[data-i]" if mobile else "#sessionsView .card[data-id]",
                                     timeout=10000)
                pg.wait_for_timeout(300)
                T = pg.evaluate("window.__tg")
                for n in ("ready", "expand", "disableVerticalSwipes", "BackButton.onClick"):
                    assert n in T["calls"], f"{tag}: не вызван Telegram.WebApp.{n} ({T['calls']})"
                assert {"themeChanged", "viewportChanged"} <= set(T["events"]), f"{tag}: подписки {T['events']}"
                theme = pg.evaluate("document.documentElement.dataset.theme")
                assert theme == scheme, f"{tag}: тема страницы {theme}, а в Telegram {scheme}"
                canvas = pg.evaluate("getComputedStyle(document.documentElement)"
                                     ".getPropertyValue('--bg-canvas').trim()")
                kinds = {k for k, c in T["colors"] if c == canvas}
                assert canvas and kinds >= {"header", "bg"}, f"{tag}: цвета Telegram {T['colors']} ≠ {canvas}"
                def bb(pg=pg):
                    return pg.evaluate("Telegram.WebApp.BackButton.isVisible")
                if mobile:
                    assert pg.evaluate("view") == "session", f"{tag}: телефон не открыл сессию"
                    assert bb(), f"{tag}: в сессии нет кнопки Telegram «Назад»"
                    if out:
                        pg.screenshot(path=str(out / f"miniapp-{w}-{scheme}-session.png"))
                    pg.evaluate("window.__tg.back()")
                    pg.wait_for_selector("#sessionsView .card[data-id]", timeout=5000)
                    assert pg.evaluate("view") == "home", f"{tag}: «Назад» Telegram не вернула на главную"
                    assert not bb(), f"{tag}: на главной осталась кнопка «Назад»"
                else:
                    assert pg.evaluate("view") == "home", f"{tag}: компьютер — не главная"
                    assert not bb(), f"{tag}: на главной компьютера видна «Назад»"
                if out:
                    pg.screenshot(path=str(out / f"miniapp-{w}-{scheme}-home.png"))
                pages = len(ctx.pages)
                pg.evaluate("openUrl('https://ext.example/page')")
                pg.evaluate("confirmDanger('Точно?', () => { window.__went = 1; })")
                pg.wait_for_timeout(200)
                T = pg.evaluate("window.__tg")
                assert T["opened"] == ["https://ext.example/page"], f"{tag}: ссылка не через openLink {T['opened']}"
                assert len(ctx.pages) == pages, f"{tag}: открылась вкладка вместо openLink"
                assert T["confirms"] == ["Точно?"], f"{tag}: подтверждение не окном Telegram {T['confirms']}"
                assert not pg.evaluate("window.__went"), f"{tag}: «Отмена» в окне Telegram всё равно выполнила"
                wide = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
                assert wide <= 1, f"{tag}: горизонтальная прокрутка {wide}px"
                ctx.close()
                print("ok:", tag, flush=True)
        br.close()
    assert not errs, f"ошибки в консоли: {errs[:5]}"


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    print("miniapp_demo ok")
