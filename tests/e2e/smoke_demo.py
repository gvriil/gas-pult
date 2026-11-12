"""Сетка экранов демо: 390 и 1366, светлая и тёмная, основные экраны — без ошибок и без горизонтальной прокрутки.

    python tests/e2e/smoke_demo.py http://127.0.0.1:8797/?demo [папка-для-снимков]

Эталон для разбиения пульта на модули: каждый экран должен дойти до своего признака готовности, консоль чистая
(кроме недоступных внешних адресов), ширина страницы не больше окна. Снимки — ``<экран>-<ширина>-<тема>.png``.
"""

import sys
from pathlib import Path

# экран → (параметры адреса, признак готовности)
SCREENS = {
    "home": ("home", "#sessionsView .card[data-id]"),
    "session": ("open=@1&noscroll", "#content .msg[data-i]"),
    "commands": ("cmds", "#home:not([hidden]), #commandsView"),
    "integrations": ("view=integrations", "#home"),
    "projects": ("home&proj", "#projectsView .card[data-proj], #sessionsView .card[data-id]"),
    "simple": ("simple=1", "#simple:not([hidden]), .s-chat, body"),
    "login": ("view=login", ".login-bg #loginIn, #login:not([hidden])"),
    "english": ("home&lang=en", "#sessionsView .card[data-id]"),
}


def run(base: str, shots: str = ""):
    from playwright.sync_api import sync_playwright

    out = Path(shots) if shots else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    errs: list[str] = []
    sep = "&" if "?" in base else "?"
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for w in (390, 1366):
            mobile = w < 600
            ctx = br.new_context(viewport={"width": w, "height": 844 if mobile else 860}, is_mobile=mobile,
                                 has_touch=mobile)
            for th in ("light", "dark"):
                for name, (q, ready) in SCREENS.items():
                    tag = f"{name} {w} {th}"
                    pg = ctx.new_page()
                    pg.on("console", lambda m, t=tag: m.type == "error" and "Failed to load resource" not in m.text
                          and errs.append(f"{t}: {m.text}"))
                    pg.on("pageerror", lambda e, t=tag: errs.append(f"{t}: {e}"))
                    pg.goto(f"{base}{sep}{q}&theme={th}")
                    pg.wait_for_selector(ready, timeout=10000, state="attached")
                    pg.wait_for_timeout(700)
                    assert pg.evaluate("document.documentElement.dataset.theme") == th, f"{tag}: тема"
                    wide = pg.evaluate("document.documentElement.scrollWidth - innerWidth")
                    assert wide <= 1, f"{tag}: горизонтальная прокрутка {wide}px"
                    if out:
                        pg.screenshot(path=str(out / f"{name}-{w}-{th}.png"))
                    pg.close()
                print(f"ok: {w} {th}", flush=True)
            ctx.close()
        br.close()
    assert not errs, f"ошибки в консоли: {errs[:5]}"


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    print("smoke_demo ok")
