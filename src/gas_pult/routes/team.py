"""Маршруты области «Сообщения команды» (teammsg.py, владелец 22.11): «Команда» пишет в чат окна или проекта, человек
жмёт «Сообщить об ошибке» у поля ввода.

Права (``access.py``: ``TEAM_SAY`` — ``OWNER_ONLY``; ``BUG`` — каждый, кто видит чат: ``SPACE_OK``, ``FOCUS_POST``)
проверены до вызова — ``H.permit`` или ``H.focus_call`` (у фокус-ссылки окно ``w`` — только её). Окно отчёта —
``POST_W``: ``self.win(b["w"])`` в области видимости запроса (пространство, ссылка). Таблицы и подписи —
``routes/__init__.py``.
"""


def team_say(self, b: dict):
    """POST /api/team/say — сообщение команды в чат окна (``w``) или проекта (``proj``); в Claude не уходит"""
    panel = self.panel
    return panel.team_say(b)


def bug(self, b: dict, w: dict):
    """POST /api/bug — «Сообщить об ошибке»: задача владельцу, уведомление, человеку — «Приняли»"""
    panel = self.panel
    return panel.bug_report(self.who(), w, b, self.client()[1], self.focused)


POST = {"/api/team/say": team_say}
POST_W = {"/api/bug": bug}
