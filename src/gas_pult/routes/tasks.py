"""Маршруты области «Задачи и брифинг» (MONOLITH-PLAN §3.2, шаг 7): задачи владельца (#203) и брифинг (GAS-18).

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Права (``access.py``: ``OWNER_ONLY``, ``BRIEF``; ``/api/tasks/run`` — ``CONFIRM``) проверены до
вызова — ``H.permit``; через ``/api/v1`` — ``H.v1_call`` (``V1_*``: ``/api/tasks``, ``/api/tasks/add``,
``/api/tasks/update``). Таблицы и подписи — ``routes/__init__.py``.
"""

import json

from gas_pult.routes import SENT


def brief(self, q: dict):
    """GET /api/brief — брифинг (GAS-18): собирает код, без модели"""
    panel = self.panel
    return panel.brief_get(self.terms_uid(), q.get("fresh") == "1")


def tasks(self, q: dict):
    """GET /api/tasks — задачи владельца (#203): не менялись — 304 без тела"""
    panel = self.panel
    etag = panel.tasks.etag()
    body = json.dumps({"tasks": panel.task_list()}, ensure_ascii=False).encode()
    self.reply(200, body, etag=etag)
    return SENT


def brief_prefs(self, b: dict):
    """POST /api/brief/prefs — брифинг: источники, время, дни, пояс — у каждого свои"""
    panel = self.panel
    return panel.brief_set(self.terms_uid(), b)


def brief_act(self, b: dict):
    """POST /api/brief/act — «Да / Нет / Позже»; «Да» с действием — после confirm"""
    panel = self.panel
    out = panel.brief_act(self.terms_uid(), b)
    if b.get("act") in ("yes", "no") and "ask" not in out:    # «Да» с действием — после подтверждения
        self.product(str(b["act"]), via="brief")
    return out


def tasks_add(self, b: dict):
    """POST /api/tasks/add — задача владельца руками (#203)"""
    panel = self.panel
    return panel.tasks.add(b, by="owner")


def tasks_update(self, b: dict):
    """POST /api/tasks/update — статус, «что дальше» и поля задачи"""
    panel = self.panel
    return panel.tasks.update(str(b.get("id") or ""), {k: v for k, v in b.items() if k != "id"})


def tasks_remove(self, b: dict):
    """POST /api/tasks/remove"""
    panel = self.panel
    return {"ok": panel.tasks.remove(str(b.get("id") or ""))}


def tasks_run(self, b: dict):
    """POST /api/tasks/run — «Выполнить» команду задачи — с подтверждением кодом"""
    panel = self.panel
    return panel.task_run(str(b.get("id") or ""), b.get("confirmed") is True)


GET = {"/api/brief": brief, "/api/tasks": tasks}
POST = {"/api/brief/prefs": brief_prefs, "/api/brief/act": brief_act, "/api/tasks/add": tasks_add,
        "/api/tasks/update": tasks_update, "/api/tasks/remove": tasks_remove, "/api/tasks/run": tasks_run}
