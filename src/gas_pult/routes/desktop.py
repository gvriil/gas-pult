"""Маршруты «Рабочий стол», ссылки сайтов и «Терминал» (MONOLITH-PLAN §3.2, шаг 7): ссылка — вкладкой в Chrome
рабочего стола, где открывать ссылки сайтов («Запомнить для этого сайта» / «Забыть»), окно «Терминал»
(``ubuntu-shell``), «Рабочий стол» (пропуск и одноразовая ссылка вкладки), мобильный вид сайтов и вкладки Chrome стола
на телефоне (развилка ``POST_P``).

Ветки перенесены из ``webapp.H.get``/``H.post`` как есть: ``self`` — обработчик запроса (``webapp.H``), ``panel`` —
его ``Panel``. Функции стола — модуль ``gas_pult/desktop.py`` (раньше — верхний уровень ``webapp``): ``desktop_up``,
``desktop_tab``, ``shell_window`` берутся оттуда при каждом вызове (строка ``x = desktop.x`` — тело как было; тесты
подменяют их в ``desktop``). Права — до вызова, ``H.permit``: ``OWNER_ONLY``, код подтверждения нового входа
(``CONFIRM``) для «Рабочего стола» и «Терминала»; по фокус-ссылке — нет. Вход на стол — до ``permit``, в
``webapp.do_GET`` (``/api/gate/desktop``, ``/desktop-enter``). Таблицы и подписи — ``routes/__init__.py``.
"""

from gas_pult import deskmobile, desktabs, desktop, webauth
from gas_pult.desktop import (
    DESKTOP_URL,
    SHELL_WINDOW,
    desk_cookie,
    desk_pass,
    desk_ticket,
    link_pref_set,
    link_prefs,
)


def links_get(self, q: dict):
    """GET /api/links/prefs — где открывать ссылки сайтов (только владелец)"""
    panel = self.panel
    return {"sites": link_prefs(panel.cfg.data)}


def desktop_url(self, b: dict):
    """POST /api/desktop/url — ссылка — вкладкой в Chrome рабочего стола (владелец 17.11)"""
    desktop_up = desktop.desktop_up
    desktop_tab = desktop.desktop_tab
    if not desktop_up():
        raise ValueError("рабочий стол не запущен на сервере (agent-desktop)")
    return desktop_tab(str(b.get("url") or ""))


def links_set(self, b: dict):
    """POST /api/links/prefs — «Запомнить для этого сайта» / «Забыть» в Настройках"""
    panel = self.panel
    return {"sites": link_pref_set(panel.cfg.data, str(b.get("host") or ""), b.get("open"))}


def shell_open(self, b: dict):
    """POST /api/shell/open — «Терминал» рядом с «Ubuntu»: окно ubuntu-shell"""
    panel = self.panel
    shell_window = desktop.shell_window
    with panel.tmux.scope(None):
        return {"id": shell_window(panel.tmux), "name": SHELL_WINDOW}


def desktop_open(self, b: dict):
    """POST /api/desktop/open — «Рабочий стол» (#206): код подтверждения — через CONFIRM"""
    desktop_up = desktop.desktop_up
    if not desktop_up():
        raise ValueError("рабочий стол не запущен на сервере (agent-desktop)")
    uid = self.who()[2]
    uid = uid if uid is not None else webauth.LEGACY
    return ("cookie", desk_cookie(desk_pass(uid)),
            {"url": DESKTOP_URL, "tab": "/desktop-enter?t=" + desk_ticket(uid)})


def desktop_mobile(self, b: dict):
    """POST /api/desktop/mobile — мобильный вид сайтов, пока стол смотрят с телефона (21.11)"""
    desktop_up = desktop.desktop_up
    on = bool(b.get("on"))
    if on and not desktop_up():
        raise ValueError("рабочий стол не запущен на сервере (agent-desktop)")
    return deskmobile.MOBILE.set(on, b.get("w"), b.get("h"), b.get("dpr"))


def desktop_tabs(self, path: str, b: dict):
    """POST_P /api/desktop/tabs, /api/desktop/tabs/shot|act — вкладки Chrome стола на телефоне"""
    desktop_up = desktop.desktop_up
    if not desktop_up():                      # вкладки Chrome стола на телефоне (desktabs.py, 22.11)
        raise ValueError("рабочий стол не запущен на сервере (agent-desktop)")
    if path == "/api/desktop/tabs":
        return desktabs.TABS.list(b.get("idle"))
    if path == "/api/desktop/tabs/shot":
        return desktabs.TABS.shot(str(b.get("id") or ""))
    return desktabs.TABS.act(str(b.get("op") or ""), str(b.get("id") or ""), str(b.get("url") or ""))


GET = {"/api/links/prefs": links_get}
POST = {"/api/desktop/url": desktop_url, "/api/links/prefs": links_set, "/api/shell/open": shell_open,
        "/api/desktop/open": desktop_open, "/api/desktop/mobile": desktop_mobile}
POST_P = {("/api/desktop/tabs", "/api/desktop/tabs/shot", "/api/desktop/tabs/act"): desktop_tabs}
