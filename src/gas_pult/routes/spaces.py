"""Маршруты области «Пространства» (MONOLITH-PLAN §3.2, шаг 7): пространства и их бюджет (задача 35), закрытые сессии
пространства и корзина, свои интеграции пространства (GAS-38 (в)), файлы папки сессии, «Поставить задачу»,
«Подключиться» владельца к окну пространства.

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Граница пространств — внутри функций, как в цепочке: чьё пространство — ``self.space_of`` (человеку
пространства — только его, владельцу и админу — из запроса), ``self.space()``, окно — ``self.space_win`` (человеку
пространства — только окно его пространства). Права (``access.py``: ``SPACE_OK``, ``OWNER_ONLY``, ``ADMIN_OK``,
``BUDGET_PATHS``; фокус-ссылка — ``FOCUS_*``: ``/api/space/files|download``, ``/api/space/upload``; «Завершить» по
фокус-ссылке — ``H.focus_do``, не здесь) проверены до вызова — ``H.permit`` или ``H.focus_call``.
``/api/space/upload`` — ``POST_RAW`` (файл, тело читает сама); ``/api/space/connect`` — ``POST_W`` (ветка шла после
``w = self.win(b.get("w"))``). Таблицы и подписи — ``routes/__init__.py``.
"""

import urllib.parse

from gas_pult import mcp, space_files, space_mcp, tenants
from gas_pult.routes import consent


def spaces_list(self, q: dict):
    """GET /api/spaces — владелец: пространства для «Поставить задачу»"""
    panel = self.panel
    st = tenants.status(check=True)
    for x in st.get("tenants", []):            # и запас каждого на период (задача 35)
        x["budget"] = panel.space_budget(x["slug"])
    return st


def space_sessions(self, q: dict):
    """GET /api/space/sessions — закрытые сессии пространства и корзина"""
    panel = self.panel
    return panel.space_list(self.space_of(q))


def space_mcp_list(self, q: dict):
    """GET /api/space/mcp — свои интеграции пространства (GAS-38 (в)): без ключей"""
    slug = self.space_of(q)                      # тестировщику — своё; владельцу и админу — по ``space``
    return {"servers": space_mcp.listing(slug), "space": slug,
            "presets": space_mcp.presets() if self.space() else []}


def space_files_get(self, path: str, q: dict):
    """GET_P /api/space/files|download — файлы папки сессии пространства"""
    slug, w = self.space_win(q)
    folder = space_files.folder_of(slug, w)
    if path == "/api/space/files":
        return space_files.listing(slug, folder)
    name, data = space_files.get(slug, folder, q.get("f", ""))
    disp = "attachment; filename*=UTF-8''" + urllib.parse.quote(name)
    return ("application/octet-stream", data, {"Content-Disposition": disp})


def space_upload(self):
    """POST /api/space/upload — файл — в папку сессии пространства (от его пользователя)"""
    slug, w = self.space_win(dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query)))
    name = urllib.parse.unquote(self.headers.get("X-File-Name", "file"))
    return {"name": space_files.put(slug, space_files.folder_of(slug, w), name, self.body())}


def space_budget_add(self, b: dict):
    """POST /api/space/budget/add — владелец: «+ добавить» к запасу пространства"""
    panel = self.panel
    return panel.budget_add(tenants.check_slug(str(b.get("space", ""))), float(b.get("usd") or 0),
                            self.terms_uid())


def space_close(self, b: dict):
    """POST /api/space/close"""
    panel = self.panel
    r = panel.space_close(self.space_of(b), str(b.get("w", "")), b.get("force") is True)
    if r.get("result") == "closed":
        panel.focus.end_window(str(b.get("w", "")))
    return r


def space_mcp_change(self, path: str, b: dict):
    """POST_P /api/space/mcp/add|remove — только в своём пространстве (GAS-38 (в))"""
    if not (slug := self.space()):
        raise ValueError("интеграции пространства меняет его человек; владелец — pult-tenant mcp")
    if path.endswith("/add"):
        if any(p["id"] == str(b.get("preset", "")) for p in mcp.PRESETS):   # неизвестный шаблон — прежние 400
            consent.require(self, "mcp:" + str(b.get("preset", "")))
        return space_mcp.add(slug, str(b.get("preset", "")), str(b.get("name", "")), b.get("values") or {})
    return space_mcp.remove(slug, str(b.get("name", "")))


def space_resume(self, b: dict):
    """POST /api/space/resume"""
    panel = self.panel
    return panel.space_resume(self.space_of(b), str(b.get("folder", "")))


def space_delete(self, b: dict):
    """POST /api/space/delete"""
    panel = self.panel
    return panel.space_delete(self.space_of(b), str(b.get("folder", "")), str(b.get("confirm", "")))


def space_restore(self, b: dict):
    """POST /api/space/restore"""
    panel = self.panel
    return panel.space_restore(self.space_of(b), str(b.get("id", "")))


def space_task(self, b: dict):
    """POST /api/space/task"""
    panel = self.panel
    return panel.space_task(str(b.get("space", "")), str(b.get("name", "")), str(b.get("task", "")))


def space_connect(self, b: dict, w: dict):
    """POST_W /api/space/connect"""
    panel = self.panel
    return panel.owner_join(w)


GET = {"/api/spaces": spaces_list, "/api/space/sessions": space_sessions, "/api/space/mcp": space_mcp_list}
GET_P = {("/api/space/files", "/api/space/download"): space_files_get}
POST_RAW = {"/api/space/upload": space_upload}
POST = {"/api/space/budget/add": space_budget_add, "/api/space/close": space_close, "/api/space/resume": space_resume,
        "/api/space/delete": space_delete, "/api/space/restore": space_restore, "/api/space/task": space_task}
POST_P = {("/api/space/mcp/add", "/api/space/mcp/remove"): space_mcp_change}
POST_W = {"/api/space/connect": space_connect}
