"""Маршруты области «Фокус-ссылки» (MONOLITH-PLAN §3.2, шаг 7): «Фокус-ссылка» из меню сессии и проекта,
«Ссылка на пространство» (GAS-38), «Отправить себе в Telegram», QR, «Браузер» для ссылки, список и отзыв.

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Две ветки ``/api/focus/new`` — одна функция (``if path == P and X`` → ``if X``). Права (``access.py``:
``OWNER_ONLY`` — все пути области) проверены до вызова — ``H.permit``. Свой компьютер гостя по фокус-ссылке
(``/api/focus/bridge*``) — ``Panel.focus_bridge`` (``panel/focus.py``) из ``H.focus_do``: этих путей нет вне ссылки;
вход по ссылке ``/api/focus/open`` — до входа, в ``do_POST``. Таблицы и подписи — ``routes/__init__.py``.
"""

from gas_pult import qr


def focus_list(self, q: dict):
    """GET /api/focus/list — «Настройки» → «Фокус-ссылки»: действующие, без токенов"""
    panel = self.panel
    return {"links": panel.focus.listing()}


def focus_new(self, b: dict):
    """POST /api/focus/new — «Ссылка на пространство» (GAS-38); «Фокус-ссылка» из меню сессии"""
    panel = self.panel
    if b.get("space"):   # «Ссылка на пространство» (GAS-38)
        return panel.focus_space(str(b["space"]), self.terms_uid(), str(b.get("base", "")),
                                 str(b.get("ttl") or "7d"), int(b.get("max", 3) or 0),
                                 str(b.get("rights") or "full"), str(b.get("name") or ""),
                                 str(b.get("audience") or "client"))
    return panel.focus_new(str(b.get("w", "")), self.terms_uid(), str(b.get("base", "")),
                           str(b.get("proj") or ""), str(b.get("mode") or ""))


def focus_send(self, b: dict):
    """POST /api/focus/send — «Отправить себе в Telegram»"""
    panel = self.panel
    return panel.focus_send(str(b.get("url", "")), self.terms_uid())


def focus_qr(self, b: dict):
    """POST /api/focus/qr — QR — POST: адрес с токеном не попадает в журнал прокси"""
    panel = self.panel
    panel.focus_token(str(b.get("url", "")))
    return ("image/png", qr.png_of(str(b["url"])))


def focus_browser(self, b: dict):
    """POST /api/focus/browser — фокус-ссылка: разрешить подключить свой браузер"""
    panel = self.panel
    return {"ok": panel.focus.set_browser(str(b.get("id", "")), bool(b.get("on", True)))}


def focus_revoke(self, b: dict):
    """POST /api/focus/revoke"""
    panel = self.panel
    return {"ok": panel.focus.revoke(str(b.get("id", ""))), "links": panel.focus.listing()}


def focus_asks(self, q: dict):
    """GET /api/focus/asks — запрос доступа «Попросить доступ» и его ссылка (кнопка в сообщении владельцу)"""
    panel = self.panel
    return panel.focus.ask_get(str(q.get("id", "")))


def focus_device(self, b: dict):
    """POST /api/focus/device — «Добавить устройство»: одноразовая ссылка той же записи на 15 минут и QR.
    С устройства по фокус-ссылке тот же путь обрабатывает ``H.focus_do`` — только своя запись."""
    panel = self.panel
    return panel.focus_device(str(b.get("id", "")), str(b.get("base", "")))


GET = {"/api/focus/list": focus_list, "/api/focus/asks": focus_asks}
POST = {"/api/focus/new": focus_new, "/api/focus/send": focus_send, "/api/focus/qr": focus_qr,
        "/api/focus/browser": focus_browser, "/api/focus/revoke": focus_revoke, "/api/focus/device": focus_device}
