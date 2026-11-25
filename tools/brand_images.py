"""Картинки бренда из знака «Лад» (web/brand/ladeya-mark*.svg, значок — ladeya-app-icon.svg): значки вкладки и экрана
«Домой», превью ссылки (og), экраны запуска iOS, maskable-иконка.
Рисует браузер (Playwright, как в тестах интерфейса) — без новых зависимостей ядра. Запуск из корня репозитория:
    python tools/brand_images.py
Пересобирать после смены знака или названия. Владелец 21.11: «миниатюра для PWA должна быть с лого»."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from gas_pult import brand

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "src/gas_pult/web/brand"
MARK = {"light": (BRAND / "ladeya-mark.svg").read_text(encoding="utf-8"),          # чёрные палочки + красная
        "dark": (BRAND / "ladeya-mark-dark.svg").read_text(encoding="utf-8")}
APP = (BRAND / "ladeya-app-icon.svg").read_text(encoding="utf-8")                # значок 512: тёмный фон
THEMES = {"light": ("#F4F4F2", "#111111", "#4B5563"), "dark": ("#111111", "#F2F2F2", "#9CA3AF")}   # фон, знак, подпись
# iPhone: CSS-ширина × высота × плотность (портрет) — экраны запуска apple-touch-startup-image
IPHONES = [(440, 956, 3), (430, 932, 3), (428, 926, 3), (402, 874, 3), (393, 852, 3), (390, 844, 3), (375, 812, 3),
           (375, 667, 2)]
FONT = "'Noto Sans', Inter, -apple-system, 'Segoe UI', Roboto, sans-serif"   # картинки рисуются на сервере: Noto есть


def page(w, h, bg, body):
    return (f'<html><body style="margin:0;width:{w}px;height:{h}px;background:{bg};display:flex;align-items:center;'
            f'justify-content:center;font-family:{FONT}">{body}</body></html>')


def mark(size, theme="dark", src=None):
    svg = (src or MARK[theme]).replace("<svg ", '<svg width="100%" height="100%" ', 1)
    return f'<div style="width:{size}px;height:{size}px">{svg}</div>'


def main():
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch()

        def shot(name, w, h, html, scale=1, clear=False):
            pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
            pg.set_content(html)
            pg.screenshot(path=str(BRAND / name), omit_background=clear)
            pg.close()
            out.append(name)

        bg, fg, sub = THEMES["dark"]                     # превью ссылки: знак + «Ladeya by Botsmith» (25.11)
        shot("og-1200x630.png", 1200, 630, page(1200, 630, bg, '<div style="display:flex;align-items:center;gap:40px">'
             + mark(260) + f'<div><div style="font-size:120px;font-weight:700;letter-spacing:-.03em;color:{fg}">'
             f'{brand.APP_NAME_EN}</div><div style="font-size:40px;font-weight:500;color:{sub};margin-top:4px">'
             f'{brand.BY}</div></div></div>'))
        for name, size in (("icon-512.png", 512), ("icon-192.png", 192), ("apple-touch-180.png", 180)):   # «Домой»
            shot(name, size, size, page(size, size, bg, mark(size, src=APP)))   # значок приложения целиком
        for t in THEMES:                                 # вкладка: прозрачный фон, знак во всю ширину
            shot("favicon-32.png" if t == "light" else "favicon-32-dark.png", 32, 32,
                 page(32, 32, "transparent", mark(32, t)), clear=True)
        bg, fg, _ = THEMES["dark"]                       # maskable: знак в безопасной зоне (круг 80 %) — высота 56 %
        shot("icon-maskable-512.png", 512, 512, page(512, 512, bg, mark(300)))   # знак в безопасной зоне (круг 80 %)
        for t, (bg, fg, _) in THEMES.items():            # экраны запуска iOS: знак по центру, имя под ним
            for w, h, s in IPHONES:
                shot(f"splash-{w}x{h}-{t}.png", w, h, page(w, h, bg, f'<div style="text-align:center">{mark(120, t)}'
                     f'<div style="font-size:22px;font-weight:600;color:{fg};margin-top:8px">'
                     f'{brand.APP_NAME_RU}</div></div>'), s)
        b.close()
    print("\n".join(out))


if __name__ == "__main__":
    main()
