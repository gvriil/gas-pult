"""Маршруты области «Уведомления» (MONOLITH-PLAN §3.2, шаг 7): куда и о чём сообщать (``notifyroute.py``) и
уведомления на телефон (``webpush.py``) — свои у каждого вошедшего.

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Права (``access.py``: ``PUSH_OWN`` — и наблюдателю, ``SPACE_OK``; ``SLINK_NO``) проверены до вызова —
``H.permit``; чей — ``self.push_uid()`` (фокус-ссылке и входу без ID — 400). ``/api/push/*`` — развилка
(``GET_P``/``POST_P``): одна ветка цепочки на три пути. Таблицы и подписи — ``routes/__init__.py``.
"""

PUSH_GET = ("/api/push/key", "/api/push/devices", "/api/push/last")
PUSH_POST = ("/api/push/subscribe", "/api/push/unsubscribe", "/api/push/test")


def notify_prefs(self, q: dict):
    """GET /api/notify/prefs — куда и о чём сообщать (notifyroute.py)"""
    panel = self.panel
    return panel.notify_info(self.push_uid())


def push_get(self, path: str, q: dict):
    """GET_P /api/push/key|devices|last — уведомления на телефон — свои"""
    panel = self.panel
    uid = self.push_uid()
    if path == "/api/push/key":
        return {"key": panel.push.public_key()}
    if path == "/api/push/devices":
        return {"devices": panel.push.devices(uid)}
    return {"items": panel.push.pending(uid, q.get("dev", [""])[0][:32])}


def notify_set(self, b: dict):
    """POST /api/notify/prefs"""
    panel = self.panel
    return panel.notify_set(self.push_uid(), b)


def push_post(self, path: str, b: dict):
    """POST_P /api/push/subscribe|unsubscribe|test"""
    panel = self.panel
    uid = self.push_uid()
    if path == "/api/push/subscribe":
        return panel.push.add(uid, b.get("sub") or {}, str(b.get("label") or ""),
                              "https://" + str(self.headers.get("Host") or "localhost"))
    if path == "/api/push/unsubscribe":
        return {"ok": panel.push.remove(uid, str(b.get("id") or ""))}
    n = panel.push.notify(uid, "Проверка уведомлений",
                          "Видите это — уведомления на это устройство работают.", wait=True)
    return {"devices": n, "list": panel.push.devices(uid)}


GET = {"/api/notify/prefs": notify_prefs}
GET_P = {PUSH_GET: push_get}
POST = {"/api/notify/prefs": notify_set}
POST_P = {PUSH_POST: push_post}
