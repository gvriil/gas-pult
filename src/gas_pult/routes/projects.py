"""Маршруты области «Проекты и чаты» (MONOLITH-PLAN §3.2, шаг 7): «Проекты» (docs/PROJECTS.md), завершённые чаты и
их переписка, «Новая сессия в проекте» и «Продолжить», корзина чатов, «Новый проект», интеграции посреди чата.

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``, ``build`` — версия страницы (``H.build``). Граница пространств — внутри функций, как в цепочке:
проект пространства (GAS-38) — через ``self.sp``/``self.space()`` (человеку пространства — только его пространство;
две ветки одного пути — одна функция, ``if path == P and X`` → ``if X``; общая ветка проекта пространства
``/api/project/session|resume`` — по своей части в каждой из двух функций). Права (``access.py``: ``SPACE_OK``,
``OWNER_ONLY``, ``ADMIN_OK``, ``BUDGET_PATHS``; ссылка на проект — ``FOCUS_PROJ_*``; через ``/api/v1`` — группа
«sessions»: ``/api/project*``, ``/api/projects``) проверены до вызова — ``H.permit``, ``H.focus_call`` или
``H.v1_call``. ``/api/chat/mcp`` — ``POST_W``: окно ``w`` из тела ищет ``H.post`` до вызова (ветка шла после
``w = self.win(b.get("w"))``). Таблицы и подписи — ``routes/__init__.py``.
"""

import contextlib
import re
import time

from gas_pult import ctxsnap, fallback, projects


def projects_list(self, q: dict):
    """GET /api/projects — «Проекты» (docs/PROJECTS.md): список для главной; тестировщику — своего пространства"""
    panel = self.panel
    build = self.build
    if (slug := self.space()):   # тестировщик: проекты своего пространства
        sp, ss = panel.space_info(self.terms_uid()) or {}, panel.sessions(self.pool(), self.pinner())
        return {"projects": panel.space_projects_list(slug, ss, q.get("q", "")) if q.get("archived") != "1"
                else [], "order": projects.order_of(panel.project_data(), self.pinner()), "sessions": ss,
                "now": time.time(), "host": sp.get("title", ""), "build": build, "limits": None,
                "tasks": None, "new_root": "projects", "cost": panel.cost_summary(self.pool()), "fallback": [],
                "space": sp}
    pool = self.pool()
    with panel.tmux.all_spaces() if self.who()[1] in ("owner", "admin") else contextlib.nullcontext():
        ss = panel.sessions(pool, self.pinner())
    # всё, что отдаёт /api/sessions, — чтобы главной «Проекты» хватало одного запроса раз в 3 с
    return {"projects": panel.projects_list(ss, q.get("q", ""), q.get("archived") == "1", self.pinner()),
            "order": projects.order_of(panel.project_data(), self.pinner()),   # свой порядок (20.11)
            "sessions": ss, "now": time.time(), "host": panel.cfg.host, "build": build,
            "limits": ctxsnap.limits() if self.who()[1] == "owner" else None,
            "tasks": panel.tasks.open_count() if self.who()[1] == "owner" else None,   # #203
            "new_root": projects.tilde(str(panel.pult.module_root()), panel.pult.home),   # «Новый проект»
            # проекты пространств — владельцу и админу, в группе «Пространства» (GAS-38, добавлено)
            "space_projects": panel.owner_space_projects(ss) if self.who()[1] in ("owner", "admin")
            else [],
            "cost": panel.cost_summary(pool),
            "fallback": [{k: x.get(k) for k in ("ts", "w", "text")}
                         for x in fallback.recent(panel.pult.state())]}


def project(self, q: dict):
    """GET /api/project"""
    panel = self.panel
    if (sp := self.sp(q.get("id", "")))[0]:      # проект пространства (GAS-38)
        return panel.space_project_info(q.get("id", ""), sp[1])
    return panel.project_info(q.get("id", ""), self.pinner())


def project_sessions(self, q: dict):
    """GET /api/project/sessions — завершённые чаты проекта (журналы без окна)"""
    panel = self.panel
    before = float(q["before"]) if re.fullmatch(r"\d+(\.\d+)?", q.get("before", "")) else None
    if (sp := self.sp(q.get("id", "")))[0]:
        return panel.space_project_chats(q.get("id", ""), sp[1], q.get("q", ""), before)
    return panel.project_chats(q.get("id", ""), q.get("q", ""), before, self.person())


def chat_trash(self, q: dict):
    """GET /api/chat/trash — корзина чатов и скрытые чаты"""
    panel = self.panel
    return panel.chat_trash_list()


def project_history(self, q: dict):
    """GET /api/project/history — переписка завершённого чата — без окна"""
    panel = self.panel
    before = int(q["before"]) if q.get("before", "").isdigit() else None
    if (sp := self.sp(q.get("id", "")))[0]:
        return panel.space_project_history(q.get("id", ""), sp[1], q.get("sid", ""), before)
    return panel.project_history(q.get("id", ""), q.get("sid", ""), before)


def project_session(self, b: dict):
    """POST /api/project/session — «Новая сессия в проекте» — ещё одно окно, свой журнал; проект пространства
    (GAS-38) — окно в его tmux"""
    panel = self.panel
    if (sp := self.sp(b.get("id", "")))[0]:
        return panel.space_project_session(str(b.get("id", "")), sp[1], str(b.get("effort") or ""))
    return panel.project_session(str(b.get("id", "")), str(b.get("profile", "")), self.person(),
                                 self.terms_uid(), model=str(b.get("model") or ""),
                                 mcp_off=b.get("mcp_off") if isinstance(b.get("mcp_off"), list) else None,
                                 effort=str(b.get("effort") or ""))


def project_resume(self, b: dict):
    """POST /api/project/resume — «Продолжить» завершённый чат (--resume); проект пространства (GAS-38) — окно в его
    tmux"""
    panel = self.panel
    if (sp := self.sp(b.get("id", "")))[0]:         # проект пространства (GAS-38): окно — в его tmux
        return panel.space_project_resume(str(b.get("id", "")), sp[1], str(b.get("sid", "")))
    return panel.project_resume(str(b.get("id", "")), str(b.get("sid", "")), self.person(),
                                self.terms_uid())


def project_update(self, b: dict):
    """POST /api/project/update — меню проекта: название и архив (projects.json)"""
    panel = self.panel
    return panel.project_update(str(b.get("id", "")), b.get("name"), b.get("archived"))


def project_chat(self, b: dict):
    """POST /api/project/chat — переименовать / скрыть чат проекта"""
    panel = self.panel
    return panel.project_chat(str(b.get("id", "")), str(b.get("sid", "")), b.get("title"),
                              b.get("hidden"))


def chat_delete(self, b: dict):
    """POST /api/chat/delete — «Удалить» сессию или чат: окно закрыто, журнал — в корзину"""
    panel = self.panel
    return panel.chat_delete(str(b.get("w") or ""), str(b.get("id") or ""), str(b.get("sid") or ""),
                             b.get("force") is True)


def chat_move(self, b: dict):
    """POST /api/chat/move — «Перенести в проект…» (chat_move.py)"""
    panel = self.panel
    return panel.move_api(b, self.terms_uid())


def chat_restore(self, b: dict):
    """POST /api/chat/restore — «Вернуть» из корзины"""
    panel = self.panel
    return panel.chat_restore(str(b.get("id") or ""))


def project_new(self, b: dict):
    """POST /api/project/new — «Новый проект»: папка, CLAUDE.md, запись; чат — при отправке; тестировщику — папка в
    его пространстве"""
    panel = self.panel
    if (slug := self.space()):   # тестировщик: папка в его пространстве
        return panel.space_project_new(slug, str(b.get("name") or ""), str(b.get("instructions") or ""))
    return panel.project_new(str(b.get("name") or ""), str(b.get("folder") or ""),
                             str(b.get("instructions") or ""), str(b.get("profile") or ""),
                             str(b.get("model") or ""), self.person())


def chat_mcp(self, b: dict, w: dict):
    """POST_W /api/chat/mcp — интеграции посреди чата: запомнить и перезапустить с --resume"""
    panel = self.panel
    return panel.chat_mcp(w, b.get("off"), self.terms_uid())


GET = {"/api/projects": projects_list, "/api/project": project, "/api/project/sessions": project_sessions,
       "/api/chat/trash": chat_trash, "/api/project/history": project_history}
POST = {"/api/project/session": project_session, "/api/project/resume": project_resume,
        "/api/project/update": project_update, "/api/project/chat": project_chat, "/api/chat/delete": chat_delete,
        "/api/chat/move": chat_move, "/api/chat/restore": chat_restore, "/api/project/new": project_new}
POST_W = {"/api/chat/mcp": chat_mcp}
