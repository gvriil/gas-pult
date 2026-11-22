"""Маршруты области «Протоколы встреч» (MONOLITH-PLAN §3.2, шаг 7): список, протокол, запись, карточка, ссылка.

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Права (``access.py``: ``MEETINGS`` — только владельцу) проверены до вызова — ``H.permit``. Пути по
ссылке на протокол (``/api/mt*``) — не здесь: их отвечает ``Panel.meeting_public`` в ``H.focus_call``
(``access.MEETING_GET``). Таблицы и подписи — ``routes/__init__.py``.
"""


def meeting_list(self, q: dict):
    """GET /api/meetings — протоколы встреч (владелец 22.11)"""
    panel = self.panel
    return panel.meeting_list()


def meeting_view(self, q: dict):
    """GET /api/meeting"""
    panel = self.panel
    return panel.meeting_view(str(q.get("id") or ""))


def meeting_audio(self, q: dict):
    """GET /api/meeting/audio"""
    panel = self.panel
    return panel.meeting_audio(str(q.get("id") or ""))


def meeting_card(self, q: dict):
    """GET /api/meeting/card"""
    panel = self.panel
    return panel.meeting_card(str(q.get("id") or ""))


def meeting_share(self, b: dict):
    """POST /api/meeting/share — «Ссылка на протокол»: только этот протокол, 30 дней"""
    panel = self.panel
    return panel.meeting_share(str(b.get("id") or ""), self.terms_uid(), str(b.get("base", "")))


GET = {"/api/meetings": meeting_list, "/api/meeting": meeting_view, "/api/meeting/audio": meeting_audio,
       "/api/meeting/card": meeting_card}
POST = {"/api/meeting/share": meeting_share}
