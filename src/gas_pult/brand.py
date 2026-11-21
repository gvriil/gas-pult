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
         "/favicon.ico": ("favicon-32.png", "image/png")}       # /favicon.ico браузеры просят сами — PNG понимают


def manifest(name: str = NAME_RU) -> dict:
    """Манифест веб-приложения: экран «Домой» и уведомления на iPhone (iOS 16.4+ — только у такого приложения)."""
    return {"name": name, "short_name": name, "start_url": "/", "scope": "/", "display": "standalone",
            "background_color": "#FFFFFF", "theme_color": "#FFFFFF", "lang": "ru",
            "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                      {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                      {"src": "/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
                      {"src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml"}]}
