"""Название продукта, которое видит человек (владелец 20.11: «gavrila app»: латиницей — «Gavrila», по-русски —
«Гаврила»; главный адрес будет gavrila.app). Здесь — единственное место: сервер подставляет его в страницу
(``<meta name="application-name">``, ``<title>``), манифест для экрана «Домой», письма, уведомления и сообщения бота.
Код, пакет и пути остаются ``gas-pult``/«пульт». Знак — K3 (владелец 20.11: галстук, срезанный узел, лезвие с перьями),
файлы — ``web/brand/`` (источник — Диск владельца, «Бренд/Gavrila-знак-K3»)."""

NAME = "Gavrila"                   # латиницей: английский интерфейс, адрес, логотип
NAME_RU = "Гаврила"                # русский интерфейс (в русских строках — без латиницы, humanize.LATIN_OK)
DEFAULT = "Гаврила"                # так записано в web/index.html — сервер меняет его на NAME_RU, если они разные


FILES_DIR = "web/brand/"   # знак и значки: gavrila-mark.svg (currentColor), -small (≤ 24 px), png — экран «Домой»
MARK = FILES_DIR + "gavrila-mark.svg"
MARK_SMALL = FILES_DIR + "gavrila-mark-small.svg"
# адрес → (файл в web/brand/, тип): прежние адреса значков (GAS-20) сохранены, браузеры и iPhone их уже знают
ICONS = {"/favicon.svg": ("favicon.svg", "image/svg+xml"), "/favicon-32.png": ("favicon-32.png", "image/png"),
         "/favicon-32-dark.png": ("favicon-32-dark.png", "image/png"),
         "/apple-touch-icon.png": ("apple-touch-180.png", "image/png"),
         "/icon-192.png": ("icon-192.png", "image/png"), "/icon-512.png": ("icon-512.png", "image/png"),
         "/favicon.ico": ("favicon-32.png", "image/png"),       # /favicon.ico браузеры просят сами — PNG понимают
         # владелец 21.11 «миниатюра для PWA — с лого»: превью ссылки, maskable для Android (tools/brand_images.py)
         "/og.png": ("og-1200x630.png", "image/png"), "/icon-maskable-512.png": ("icon-maskable-512.png", "image/png")}
# экраны запуска iOS (apple-touch-startup-image): CSS-ширина, высота, плотность — светлый и тёмный
IPHONES = ((440, 956, 3), (430, 932, 3), (428, 926, 3), (402, 874, 3), (393, 852, 3), (390, 844, 3), (375, 812, 3),
           (375, 667, 2))
ICONS.update({f"/splash-{w}x{h}-{t}.png": (f"splash-{w}x{h}-{t}.png", "image/png")
              for w, h, _ in IPHONES for t in ("light", "dark")})
TAGLINE = "Агент делает рутину — вы подтверждаете «Да». Ответы в телефоне, голосом и кнопкой."


def head_tags() -> str:
    """Превью ссылки (Telegram, iMessage, WhatsApp), цвет панели браузера по теме и экраны запуска iOS.
    ``__ORIGIN__`` сервер заменяет на адрес панели из запроса (превью требует полный адрес картинки)."""
    og = (f'<meta name="description" content="{TAGLINE}"><meta property="og:type" content="website">'
          f'<meta property="og:site_name" content="{DEFAULT}"><meta property="og:title" content="{DEFAULT}">'
          f'<meta property="og:description" content="{TAGLINE}"><meta property="og:url" content="__ORIGIN__/">'
          '<meta property="og:image" content="__ORIGIN__/og.png"><meta property="og:image:width" content="1200">'
          '<meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image">'
          '<meta name="twitter:image" content="__ORIGIN__/og.png">'
          '<meta name="theme-color" content="#FFFFFF" media="(prefers-color-scheme: light)">'
          '<meta name="theme-color" content="#111214" media="(prefers-color-scheme: dark)">')
    splash = "".join(
        f'<link rel="apple-touch-startup-image" href="/splash-{w}x{h}-{t}.png" media="(device-width: {w}px) and '
        f'(device-height: {h}px) and (-webkit-device-pixel-ratio: {r}) and (orientation: portrait) and '
        f'(prefers-color-scheme: {t})">' for w, h, r in IPHONES for t in ("light", "dark"))
    return og + splash


def manifest(name: str = NAME_RU) -> dict:
    """Манифест веб-приложения: экран «Домой» и уведомления на iPhone (iOS 16.4+ — только у такого приложения)."""
    return {"name": name, "short_name": name, "start_url": "/", "scope": "/", "display": "standalone",
            "background_color": "#FFFFFF", "theme_color": "#FFFFFF", "lang": "ru",
            "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                      {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                      {"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
                      {"src": "/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
                      {"src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml"}]}
