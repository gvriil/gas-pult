"""Название продукта, которое видит человек (владелец 20.11: «пока «Gavriil App» вместо «Пульт»; потом сменим в одном
месте»). Здесь — единственное место: сервер подставляет его в страницу (``<meta name="application-name">``,
``<title>``), манифест для экрана «Домой», письма, уведомления и сообщения бота. Код, пакет и пути остаются
``gas-pult``/«пульт». Значок — позже, с логотипом."""

NAME = "Gavriil App"
DEFAULT = "Gavriil App"            # так записано в web/index.html — сервер меняет его на NAME, если они разные


def manifest(name: str = NAME) -> dict:
    """Манифест веб-приложения: экран «Домой» и уведомления на iPhone (iOS 16.4+ — только у такого приложения)."""
    return {"name": name, "short_name": name, "start_url": "/", "scope": "/", "display": "standalone",
            "background_color": "#FFFFFF", "theme_color": "#FFFFFF", "lang": "ru",
            "icons": [{"src": "/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
                      {"src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml"}]}
