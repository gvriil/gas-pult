"""Маршруты области «Поделиться» (MONOLITH-PLAN §3.2, шаг 7): «Поделились» — свои записи и устройства iPhone.

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Права — общие (``H.permit``: смотреть — любой вошедший, менять — участник и выше); записи и устройства —
свои (``self.terms_uid()``). Приём файлов (``/share``, ``/api/share`` с токеном устройства) — до входа, в
``do_POST``: не здесь. Таблицы и подписи — ``routes/__init__.py``.
"""


def share_list(self, q: dict):
    """GET /api/share/list — «Поделились» — только свои неразобранные записи"""
    panel = self.panel
    return panel.share_list(self.terms_uid())


def share_file(self, q: dict):
    """GET /api/share/file — миниатюра картинки своей записи"""
    panel = self.panel
    return panel.share_file(self.terms_uid(), q.get("id", ""), q.get("i", ""))


def share_devices(self, q: dict):
    """GET /api/share/devices — устройства «Поделиться» (iPhone) — свои"""
    panel = self.panel
    return {"devices": panel.share_tokens.mine(self.terms_uid())}


def share_done(self, b: dict):
    """POST /api/share/done — «Сохранить во Входящие» / отправили — запись разобрана"""
    panel = self.panel
    return panel.shares.done(self.terms_uid(), str(b.get("id", "")))


def share_device_new(self, b: dict):
    """POST /api/share/devices/new — токен «Быстрой команды»: показываем один раз"""
    panel = self.panel
    return panel.share_tokens.create(self.terms_uid(), str(b.get("name", "")))


def share_device_revoke(self, b: dict):
    """POST /api/share/devices/revoke"""
    panel = self.panel
    return panel.share_tokens.revoke(self.terms_uid(), str(b.get("id", "")))


GET = {"/api/share/list": share_list, "/api/share/file": share_file, "/api/share/devices": share_devices}
POST = {"/api/share/done": share_done, "/api/share/devices/new": share_device_new,
        "/api/share/devices/revoke": share_device_revoke}
