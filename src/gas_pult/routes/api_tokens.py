"""Маршруты области «Токены для 1С и CRM» (MONOLITH-PLAN §3.2, шаг 7, ``apitokens.py``): список, выпуск, отзыв.

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Права (``access.py``: ``APITOKENS`` в ``SPACE_OK``, ``SLINK_NO``, ``V1_NEVER``) проверены до вызова —
``H.permit``; чьи — ``self.api_owner()``. Вызовы по токену (``/api/v1/*``) — ``H.v1_call``: не здесь. Таблицы и
подписи — ``routes/__init__.py``.
"""

from gas_pult import apitokens


def tokens(self, q: dict):
    """GET /api/apitokens — токены для 1С и CRM (apitokens.py) — свои"""
    panel = self.panel
    return {"tokens": panel.api_tokens.mine(*self.api_owner()), "terms": apitokens.TERMS,
            "groups": apitokens.GROUPS}


def token_new(self, b: dict):
    """POST /api/apitokens/new — токен для 1С и CRM: показываем один раз"""
    panel = self.panel
    by, sp = self.api_owner()
    return panel.api_tokens.create(by, sp, str(b.get("name", "")), b.get("write") is True,
                                   b.get("days", apitokens.DEFAULT_DAYS),
                                   b.get("groups") if isinstance(b.get("groups"), list) else None)


def token_revoke(self, b: dict):
    """POST /api/apitokens/revoke"""
    panel = self.panel
    return panel.api_tokens.revoke(*self.api_owner(), str(b.get("id", "")))


GET = {"/api/apitokens": tokens}
POST = {"/api/apitokens/new": token_new, "/api/apitokens/revoke": token_revoke}
