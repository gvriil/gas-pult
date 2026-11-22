"""Маршруты области «Мессенджеры» (MONOLITH-PLAN §3.2, шаг 7): «как пользователь» — состояние, согласие, вход в
Telegram, привязка Signal / WhatsApp, чаты для модели, «Отключить» (``messengers/panel.py``).

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``). Права
(``access.py``: ``MESSENGERS`` в ``OWNER_ONLY``) проверены до вызова — ``H.permit``. Таблицы и подписи —
``routes/__init__.py``.
"""

from gas_pult import access
from gas_pult.messengers import panel as messengers_panel

# развилка «path.startswith("/api/messengers/") and path in OWNER_ONLY» из цепочки — те же пути
POST_PATHS = tuple(p for p in access.MESSENGERS if p.startswith("/api/messengers/") and p in access.OWNER_ONLY)


def messengers(self, q: dict):
    """GET /api/messengers — «Мессенджеры»: состояние без секретов (messengers/panel.py)"""
    return messengers_panel.get()


def messengers_post(self, path: str, b: dict):
    """POST_P /api/messengers/* — выбор, вход, QR, чаты, «Отключить»"""
    return messengers_panel.post(path, b, self.terms_uid())


GET = {"/api/messengers": messengers}
POST_P = {POST_PATHS: messengers_post}
