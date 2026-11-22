"""Рабочий стол агентов (#206) и то, что рядом с ним в панели: пропуск на стол (cookie ``gp_desk`` и одноразовая
ссылка вкладки), новая вкладка в Chrome стола, где открывать ссылки сайтов («Запомнить для этого сайта») и окно
«Терминал» (``ubuntu-shell``). Перенесено из верхнего уровня ``webapp.py`` как есть (MONOLITH-PLAN §4 п.7):
``webapp`` реэкспортирует имена; маршруты — ``routes/desktop.py``, ``/api/meta`` (``routes/people.py``) и вход на стол
в ``webapp`` (``/api/gate/desktop``, ``/desktop-enter``). Тесты подменяют ``desktop_up``/``desktop_tab``/
``shell_window`` здесь — маршруты берут их отсюда при каждом вызове.
"""

from __future__ import annotations

import json
import re
import secrets
import socket
import time
import urllib.parse
import urllib.request
from pathlib import Path

DESKTOP_PORT = 6080                     # noVNC/websockify рабочего стола агентов (agent-desktop.service, штаб)
DESKTOP_URL = "/desktop/vnc.html?autoconnect=1&resize=scale&reconnect=1&path=desktop/websockify"
DESK_COOKIE, DESK_TTL = "gp_desk", 12 * 3600
# Пропуск рабочего стола: выдаёт «Рабочий стол» (владельцу, после кода подтверждения). Нужен потому, что встроенный
# экран — iframe: в Mini App вход идёт заголовком Telegram, а iframe и WebSocket noVNC шлют только cookie. Живёт в
# памяти панели (перезапуск — нажать кнопку снова), путь /desktop/, 12 часов; роль владельца — на каждый запрос.
DESK_PASSES: dict[str, tuple[int, float]] = {}


def desk_pass(uid: int, now: float | None = None) -> str:
    now = now or time.time()
    for k in [k for k, (_, exp) in DESK_PASSES.items() if exp < now]:
        DESK_PASSES.pop(k, None)
    tok = secrets.token_urlsafe(24)
    DESK_PASSES[tok] = (uid, now + DESK_TTL)
    return tok


DESK_TICKETS: dict[str, tuple[int, float]] = {}   # одноразовые ссылки «Открыть в браузере»: билет → (uid, до)
TICKET_TTL = 120


def desk_ticket(uid: int, now: float | None = None) -> str:
    """Вкладка браузера (особенно из Mini App: tg.openLink — внешний браузер без cookie панели) входит по одноразовой
    ссылке /desktop-enter?t=… (2 минуты, один раз) — она ставит свой пропуск и ведёт на noVNC."""
    now = now or time.time()
    for k in [k for k, (_, exp) in DESK_TICKETS.items() if exp < now]:
        DESK_TICKETS.pop(k, None)
    t = secrets.token_urlsafe(24)
    DESK_TICKETS[t] = (uid, now + TICKET_TTL)
    return t


def desk_cookie(tok: str, tab: bool = False) -> str:
    if tab:                                       # своя вкладка браузера: обычный cookie первого лица
        return f"{DESK_COOKIE}={tok}; Path=/desktop/; Max-Age={DESK_TTL}; HttpOnly; Secure; SameSite=Lax"
    # SameSite=None + Partitioned: Mini App в Telegram Web сам открыт во фрейме — без этого cookie не дойдёт
    return f"{DESK_COOKIE}={tok}; Path=/desktop/; Max-Age={DESK_TTL}; HttpOnly; Secure; SameSite=None; Partitioned"


CDP = "http://127.0.0.1:9222"            # Chrome рабочего стола (agent-browser, профиль ~/.local/share/agent-browser)
SHELL_WINDOW = "ubuntu-shell"            # «Терминал» в панели: bash в домашней папке; gp-term — для «Выполнить»
LINK_OPEN = ("desk", "here")


def desktop_tab(url: str, cdp: str = CDP) -> dict:
    """Новая вкладка в Chrome рабочего стола: ``PUT /json/new?<адрес>`` (DevTools). Только http(s), без пробелов и
    управляющих символов. Chrome не отвечает — понятная ошибка."""
    u = str(url or "").strip()
    p = urllib.parse.urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc or len(u) > 4096 or re.search(r"[\s\x00-\x1f\x7f]", u):
        raise ValueError("открыть можно только адрес http:// или https://")
    req = urllib.request.Request(cdp + "/json/new?" + urllib.parse.quote(u, safe=":/?#[]@!$&'()*+,;=%-._~"),
                                 method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read() or b"{}")
    except (OSError, ValueError) as e:
        raise ValueError(f"браузер рабочего стола не ответил (agent-browser, порт 9222): {e}") from e
    return {"ok": True, "id": d.get("id", ""), "url": d.get("url", u)}


def link_prefs(data: Path) -> dict:
    """Где открывать ссылки сайта: {сайт: "desk" | "here"} (``link_open.json``, 0600). Решение владельца 17.11:
    «спрашивать один раз и запоминать»."""
    try:
        d = json.loads((Path(data) / "link_open.json").read_text(encoding="utf-8"))
        return {str(k): v for k, v in d.items() if v in LINK_OPEN} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def link_pref_set(data: Path, host: str, where: str | None) -> dict:
    host = str(host or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9.-]{1,253}(:\d{1,5})?", host):
        raise ValueError("неверное имя сайта")
    if where not in (*LINK_OPEN, None):
        raise ValueError("где открыть — desk или here")
    d = link_prefs(data)
    if where:
        d[host] = where
    else:
        d.pop(host, None)
    from gas_pult.config import write_private
    write_private(Path(data) / "link_open.json", json.dumps(d, ensure_ascii=False))
    return d


def shell_window(tmux) -> str:
    """Окно ``ubuntu-shell`` (bash в домашней папке) — есть, вернуть; нет — открыть в фоне. id окна."""
    w = next((x for x in tmux.windows() if x.get("name") == SHELL_WINDOW), None)
    if w:
        return w["id"]
    if hasattr(tmux, "ensure_session"):
        tmux.ensure_session()
    out = tmux.run("new-window", "-d", "-P", "-F", "#{window_id}", "-t", f"{tmux.session}:", "-n", SHELL_WINDOW,
                   "-c", str(Path.home()), "bash -l")
    if not out.strip():
        raise RuntimeError("tmux не открыл окно терминала")
    return out.split()[0]


def desktop_up(port: int = DESKTOP_PORT) -> bool:
    """Рабочий стол запущен: кто-то слушает 127.0.0.1:<port> (без него кнопку не показываем)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False
