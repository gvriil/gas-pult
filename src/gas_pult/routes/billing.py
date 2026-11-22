"""Маршруты области «Платежи» (MONOLITH-PLAN §3.2, шаг 7): тарифы и счета — развилка в ``billing.api``.

Панель знает только ``billing.api``: ветки перенесены из ``webapp.H.get``/``H.post`` как есть, ``self`` —
обработчик запроса (``webapp.H``), ``panel`` — его ``Panel``. Права (``access.py``: ``BILLING_GET`` — владельцу,
``BILLING_POST`` — владельцу после кода подтверждения) проверены до вызова — ``H.permit``. Таблицы и подписи —
``routes/__init__.py``.
"""

from gas_pult.billing import api as billing_api


def billing_get(self, path: str, q: dict):
    """GET_P /api/billing/* — платежи (billing/, 22.11): права — access.BILLING_GET"""
    panel = self.panel
    return billing_api.get(panel.cfg.data, path, q)


def billing_post(self, path: str, b: dict):
    """POST_P /api/billing/* — платежи (billing/, 22.11): владелец + код подтверждения"""
    panel = self.panel
    return billing_api.post(panel.cfg.data, path, b, actor=f"owner:{self.terms_uid()}")


GET_P = {billing_api.GET: billing_get}
POST_P = {billing_api.POST: billing_post}
