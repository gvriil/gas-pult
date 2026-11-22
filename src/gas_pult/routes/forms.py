"""Маршруты области «Анкеты клиентов» (MONOLITH-PLAN §3.2, шаг 7, 0010): личные ссылки на анкету и ответы.

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Права (``access.py``: ``OWNER_ONLY``) проверены до вызова — ``H.permit``. Сама анкета клиента
(``/api/q/*`` по ссылке) и предложения (``/api/offer/*``) — до входа, в ``do_GET``/``do_POST``: не здесь. Таблицы и
подписи — ``routes/__init__.py``.
"""

from gas_pult import onboarding


def q_list(self, q: dict):
    """GET /api/q/list — «Анкеты клиентов» (0010): ссылки без кодов и анкеты"""
    panel = self.panel
    fs = onboarding.forms(panel.cfg.data).values()
    return {"links": panel.forms_links.listing(),
            "forms": [{"id": f["id"], "title": f["title"]} for f in fs]}


def q_answers(self, q: dict):
    """GET /api/q/answers"""
    panel = self.panel
    return panel.anketa_answers(str(q.get("id") or ""))


def q_new(self, b: dict):
    """POST /api/q/new — новая личная ссылка на анкету клиента (0010)"""
    panel = self.panel
    fid = str(b.get("form") or "")
    if fid not in onboarding.forms(panel.cfg.data):
        raise ValueError("нет такой анкеты")
    r = panel.forms_links.new(fid, str(b.get("client") or ""), int(b.get("days") or onboarding.DAYS))
    return r                                   # адрес собирает панель: свой origin + path


GET = {"/api/q/list": q_list, "/api/q/answers": q_answers}
POST = {"/api/q/new": q_new}
