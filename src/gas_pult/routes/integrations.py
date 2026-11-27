"""Маршруты области «Интеграции, репозитории, модули» (MONOLITH-PLAN §3.2, шаг 7): интеграции MCP (mcp.py), ключи
календарей (calkeys.py), черновики коннекторов «Ждут вашего Да» (drafts.py), модули и репозитории сессии (39, 43).

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Права (``access.py``: ``MEMBER_ONLY`` — ``/api/mcp*``, ``OWNER_ONLY``, ``DRAFTS``, ``REPOS``, ``CONFIRM``
для ``/api/drafts/yes``; фокус-ссылка — ``FOCUS_*``: ``/api/mcp``, ``/api/mcp/connected``, ``/api/repos*``,
``/api/mcp/finish``; через ``/api/v1`` — только ``/api/drafts``) проверены до вызова — ``H.permit``, ``H.focus_call``
или ``H.v1_call``. ``/api/mcp/finish`` — ``POST_W``: окно ``w`` из тела ищет ``H.post`` до вызова (ветка шла после
``w = self.win(b.get("w"))``). Таблицы и подписи — ``routes/__init__.py``.
"""

from gas_pult import calkeys, drafts, space_mcp, tenants
from gas_pult.access import OWNER_PRESETS
from gas_pult.mcp import CARDS, CATS, CONNECTORS, CONNECTORS_URL, PRESETS
from gas_pult.routes import consent


def calendar_keys(self, q: dict):
    """GET /api/calendars/keys — что подключено — без значений секретов"""
    return {"calendars": calkeys.status()}


def mcp_list(self, q: dict):
    """GET /api/mcp — ``catalog=1``: только каталог, без опроса ``claude mcp list`` (``servers: null``) — окно
    «Подключения» открывается сразу, статусы догружаются вторым запросом. ``cats`` — разделы, ``cards`` — карточки
    без подключения кнопкой (официальный путь или «не поддерживается»). Фокус-ссылка — ``focus_list``."""
    if self.focused is not None:
        return focus_list(self, q)
    panel = self.panel
    home = self.home()
    servers = None if q.get("catalog") == "1" else panel.mcp.list(q.get("fresh") == "1", home=home)
    return {"servers": servers,
            "presets": [p for p in PRESETS if not home or p["id"] not in OWNER_PRESETS],
            "connectors": CONNECTORS, "connectors_url": CONNECTORS_URL,
            "personal": home is not None,          # список — свой у человека, не общий с владельцем
            "cats": CATS, "cards": [c for c in CARDS if not home or not c.get("owner")]}


def focus_list(self, q: dict):
    """Фокус-ссылка (правило «Чужой человек в чате — не владелец»): ресурсы владельца — его серверы, коннекторы
    claude.ai его аккаунта, почта, Telegram, Диск, ключи — не видны и не предлагаются. Ссылка в пространство — список
    своего пространства (``space_mcp``); без пространства — пусто."""
    slug = (self.focused or {}).get("space")
    servers: list = []
    if slug and q.get("catalog") != "1":
        try:
            servers = space_mcp.listing(slug)
        except (ValueError, RuntimeError, OSError):
            servers = []
    return {"servers": servers, "presets": [], "connectors": [], "connectors_url": "", "personal": True,
            "focus": True, "space": slug or "", "cats": CATS, "cards": [c for c in CARDS if not c.get("owner")]}


def modules_list(self, q: dict):
    """GET /api/modules"""
    panel = self.panel
    return panel.modules_list()


def mcp_connected(self, q: dict):
    """GET /api/mcp/connected"""
    panel = self.panel
    c = next((x for x in CONNECTORS if x["id"] == q.get("id")), None)
    if not c:
        raise LookupError("нет такого сервиса")
    if self.focused is not None:                   # коннекторы claude.ai — аккаунт владельца: по ссылке не видны
        return {"found": False, "ok": False, "state": ""}
    s = panel.mcp.connected(c["match"], self.home())
    return {"found": bool(s), "ok": bool(s and s["ok"]), "state": s["state"] if s else ""}


def drafts_list(self, q: dict):
    """GET /api/drafts — черновики коннекторов «Ждут вашего Да» (drafts.py)"""
    panel = self.panel
    slug = self.drafts_scope()
    tm = tenants.tmux_of(slug) if slug else panel.tmux
    yes = panel.approvals.pending                # «Да» уже нажато — ждёт агента, снова не показываем
    return {"drafts": drafts.pending(slug, chat_of=lambda pane: drafts.chat_of(tm, pane, slug),
                                     approved=lambda svc, pid: yes(slug or "", svc, pid))}


def repos_list(self, q: dict):
    """GET /api/repos — подключённые и что можно добавить (задача 43)"""
    panel = self.panel
    return panel.repo_list(self.repo_win(q))


def mcp_add(self, b: dict):
    """POST /api/mcp/add"""
    panel = self.panel
    home, preset = self.home(), str(b.get("preset", ""))
    if home and preset in OWNER_PRESETS:
        raise ValueError("свою программу на сервере подключает только владелец")
    if any(p["id"] == preset for p in PRESETS):    # неизвестный шаблон — прежняя ошибка 400 ниже
        consent.require(self, "mcp:" + preset)
    return {"result": panel.mcp.add(preset, str(b.get("name", "")), b.get("values") or {}, home=home)}


def mcp_remove(self, b: dict):
    """POST /api/mcp/remove"""
    panel = self.panel
    return {"result": panel.mcp.remove(str(b.get("name", "")), home=self.home())}


def calendar_key(self, b: dict):
    """POST /api/calendars/key — секрет календаря → файл 0600 и проверка (calkeys.py)"""
    kind = str(b.get("kind", ""))
    if kind in calkeys.KINDS:
        consent.require(self, "calendar:" + kind)
    return calkeys.save(kind, b)


def calendar_key_remove(self, b: dict):
    """POST /api/calendars/key/remove"""
    return calkeys.remove(str(b.get("kind", "")))


def mcp_login(self, b: dict):
    """POST /api/mcp/login"""
    panel = self.panel
    return panel.mcp_login(str(b.get("name", "")), self.home())


def drafts_answer(self, path: str, b: dict):
    """POST_P /api/drafts/yes|no — «Да» / «Нет» ровно этому черновику — только своему"""
    panel = self.panel
    self.same_origin()
    slug, svc, pid = self.drafts_scope(), str(b.get("svc", "")), str(b.get("id", ""))
    if path.endswith("/yes"):                   # «Да» — только в памяти панели (approvals.py), не на диске
        panel.approvals.grant(slug or "", svc, pid, drafts.digest(slug, svc, pid))
        r = {"ok": True}
    else:
        r = drafts.reject(slug, svc, pid)
    panel.events.event("draft_" + path.rsplit("/", 1)[1], "", svc=svc[:24])
    self.product("yes" if path.endswith("/yes") else "no", via="drafts")
    return r


def module_create(self, b: dict):
    """POST /api/modules/create"""
    panel = self.panel
    return panel.module_create(str(b.get("id", "")), str(b.get("name", "")), str(b.get("profile", "")),
                               self.person(), self.terms_uid(), str(b.get("lang", "")),
                               b.get("again") is True)


def module_schedule(self, path: str, b: dict):
    """POST_P /api/module/schedule|delete — пространство из модуля (задача 39)"""
    panel = self.panel
    w = panel.tmux.window(str(b.get("w") or ""))
    if not w:
        raise LookupError("окна уже нет")
    if path == "/api/module/schedule":
        return panel.set_schedule(w["path"], str(b.get("state", "")), self.terms_uid())
    return panel.module_delete(w, str(b.get("confirm", "")))


def repos_change(self, path: str, b: dict):
    """POST_P /api/repos/add|remove — задача 43: клон и /add-dir; «Отключить»"""
    panel = self.panel
    w = self.repo_win(b)
    if path == "/api/repos/add":
        return panel.repo_add(w, str(b.get("repo", "")))
    return panel.repo_remove(w, str(b.get("path", "")))


def mcp_finish(self, b: dict, w: dict):
    """POST_W /api/mcp/finish"""
    panel = self.panel
    return {"result": panel.mcp_finish(w, str(b.get("url", "")), str(b.get("name", "")), self.home())}


GET = {"/api/calendars/keys": calendar_keys, "/api/mcp": mcp_list, "/api/modules": modules_list,
       "/api/mcp/connected": mcp_connected, "/api/drafts": drafts_list, "/api/repos": repos_list}
POST = {"/api/mcp/add": mcp_add, "/api/mcp/remove": mcp_remove, "/api/calendars/key": calendar_key,
        "/api/calendars/key/remove": calendar_key_remove, "/api/mcp/login": mcp_login,
        "/api/modules/create": module_create}
POST_P = {("/api/drafts/yes", "/api/drafts/no"): drafts_answer,
          ("/api/module/schedule", "/api/module/delete"): module_schedule,
          ("/api/repos/add", "/api/repos/remove"): repos_change}
POST_W = {"/api/mcp/finish": mcp_finish}
