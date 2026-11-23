"""Маршруты области «Согласие на подключение» (владелец 23.11, ``consents.py``): текст экрана согласия, что уже
подтверждено, и запись «Понимаю: аккаунт мой, ответственность моя».

``self`` — обработчик запроса (``webapp.H``). Права (``access.py``: ``CONSENT`` — участник и выше, тестировщик
пространства, фокус-ссылка; через ``/api/v1`` — никогда) проверены до вызова — ``H.permit`` или ``H.focus_call``.
``require(self, what)`` зовут пути подключения (``/api/mcp/add``, ``/api/keys``, ``/api/calendars/key``,
``/api/space/mcp/add``, ``/api/messengers/consent``, ``/api/openrouter/start``): без согласия — 409 ``code=consent``.
"""

from gas_pult import consents


def who(self) -> str:
    """Чьё согласие: фокус-ссылка — её пространство (или сама ссылка), иначе — вошедший человек."""
    rec = self.focused
    if rec is not None:
        return f"space:{rec['space']}" if rec.get("space") else f"focus:{rec.get('id', '')}"
    return f"uid:{self.terms_uid()}"


def require(self, what: str) -> None:
    consents.require(consents.path_of(self.panel.cfg.data), who(self), consents.check_what(what))


def consent_get(self, q: dict):
    """GET /api/consent — текст экрана согласия, версия ``v`` и что уже подтверждено (``given``)"""
    return consents.public(consents.path_of(self.panel.cfg.data), who(self))


def consent_post(self, b: dict):
    """POST /api/consent — записать согласие на подключение ``what`` (``mcp:<id>``, ``connector:<id>``,
    ``messenger:<id>``, ``key:<id>``, ``calendar:<id>``) на текущую версию текста; без ``accepted: true`` — 400"""
    if b.get("accepted") is not True:
        raise ValueError("отметьте «" + consents.CHECK + "»")
    path = consents.path_of(self.panel.cfg.data)
    rec = consents.record(path, who(self), str(b.get("what", "")), str(b.get("title", "")))
    return {"ok": True, "consent": rec, "v": consents.CONSENT_V}


GET = {"/api/consent": consent_get}
POST = {"/api/consent": consent_post}
