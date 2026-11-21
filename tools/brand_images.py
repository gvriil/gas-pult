"""Картинки бренда из знака K3 (web/brand/gavrila-mark.svg): превью ссылки (og), экраны запуска iOS, maskable-иконка.
Рисует браузер (Playwright, как в тестах интерфейса) — без новых зависимостей ядра. Запуск из корня репозитория:
    python tools/brand_images.py
Пересобирать после смены знака или названия. Владелец 21.11: «миниатюра для PWA должна быть с лого»."""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "src/gas_pult/web/brand"
MARK = (BRAND / "gavrila-mark.svg").read_text(encoding="utf-8")
THEMES = {"light": ("#F4F4F2", "#111111", "#4B5563"), "dark": ("#111111", "#F2F2F2", "#9CA3AF")}   # фон, знак, подпись
# iPhone: CSS-ширина × высота × плотность (портрет) — экраны запуска apple-touch-startup-image
IPHONES = [(440, 956, 3), (430, 932, 3), (428, 926, 3), (402, 874, 3), (393, 852, 3), (390, 844, 3), (375, 812, 3),
           (375, 667, 2)]
FONT = "'Noto Sans', Inter, -apple-system, 'Segoe UI', Roboto, sans-serif"   # картинки рисуются на сервере: Noto есть


def page(w, h, bg, body):
    return (f'<html><body style="margin:0;width:{w}px;height:{h}px;background:{bg};display:flex;align-items:center;'
            f'justify-content:center;font-family:{FONT}">{body}</body></html>')


def mark(size, color):
    svg = MARK.replace("<svg ", '<svg width="100%" height="100%" ', 1)
    return f'<div style="width:{size}px;height:{size}px;color:{color}">{svg}</div>'


def main():
    out = []
    with sync_playwright() as p:
        b = p.chromium.launch()

        def shot(name, w, h, html, scale=1):
            pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
            pg.set_content(html)
            pg.screenshot(path=str(BRAND / name))
            pg.close()
            out.append(name)

        bg, fg, sub = THEMES["light"]                    # превью ссылки: светлое, знак слева, имя и строка справа
        name = f'<div style="font-size:112px;font-weight:700;color:{fg};letter-spacing:-.02em">Гаврила</div>'
        line = (f'<div style="font-size:36px;color:{sub};margin-top:12px;max-width:640px;line-height:1.3">'
                "Агент делает рутину — вы подтверждаете «Да»</div>")
        shot("og-1200x630.png", 1200, 630, page(1200, 630, bg, '<div style="display:flex;align-items:center;gap:56px">'
             f"{mark(300, fg)}<div>{name}{line}</div></div>"))
        bg, fg, _ = THEMES["dark"]                       # maskable: знак в безопасной зоне (круг 80 %) — высота 56 %
        shot("icon-maskable-512.png", 512, 512, page(512, 512, bg, mark(286, fg)))
        for t, (bg, fg, _) in THEMES.items():            # экраны запуска iOS: знак по центру, имя под ним
            for w, h, s in IPHONES:
                shot(f"splash-{w}x{h}-{t}.png", w, h, page(w, h, bg, f'<div style="text-align:center">{mark(120, fg)}'
                     f'<div style="font-size:22px;font-weight:600;color:{fg};margin-top:8px">Гаврила</div></div>'), s)
        b.close()
    print("\n".join(out))


if __name__ == "__main__":
    main()
