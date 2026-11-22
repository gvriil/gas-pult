"""Вкладки Chrome рабочего стола агентов на телефоне — как в мобильных браузерах (владелец 22.11).

«Вкладки Chrome на узком экране превращаются в мелкие точки: не видно, где что, непонятно, как закрыть вкладку.
Нужно как в Safari». Панель показывает свой экран вкладок (сетка карточек: миниатюра, заголовок, значок сайта, крестик,
«+»), строку адреса и «Назад / Вперёд», а полосу вкладок и адресную строку самого Chrome в картинке стола обрезает.

Откуда что (DevTools, ``127.0.0.1:9222``; только стандартная библиотека, WebSocket — ``deskmobile.Conn``):

* список — ``GET /json``: вкладки ``type == "page"`` идут от последней активной к давней, первая — открытая сейчас
  (проверено на живом Chrome 22.11: у первой ``document.visibilityState == "visible"``, у остальных ``hidden``);
* миниатюра — ``Page.captureScreenshot`` (JPEG, качество 45, ``clip.scale`` до ширины ``THUMB`` точек), кэш ``SHOT_TTL``
  секунд; фоновые вкладки Chrome тоже снимает (последний кадр вкладки);
* значок сайта — только ``data:``-значок из ``/json`` (``faviconUrl``); адрес значка на чужом сайте не запрашиваем —
  панель рисует букву домена (без внешних запросов);
* где начинается страница в картинке стола — ``Browser.getWindowForTarget`` (окно Chrome: ``top`` и ``height`` в точках
  экрана) минус высота области страницы из ``Page.getLayoutMetrics``: ``cssVisualViewport.clientHeight × zoom × scale``
  (CSS-точки → точки экрана; ``zoom`` ≠ 1 при мобильной эмуляции, ``scale`` — щипок). Живой Chrome 22.11: окно 1009,
  область 1776 × 0,5 = 888, верх страницы — 121 точка (то же, что ``outerHeight - innerHeight`` у вкладки без эмуляции).
  ``outerHeight - innerHeight`` не годится: при мобильной эмуляции ``innerHeight`` — в точках макета (1776),
  а не экрана;
* открыть / закрыть / новая — ``/json/activate/<id>``, ``/json/close/<id>``, ``PUT /json/new?about:blank``
  (HTTP-двойники ``Target.activateTarget`` / ``closeTarget`` / ``createTarget``: без подключения к браузеру);
* адрес, «Назад», «Вперёд» — ``Page.navigate``, ``Page.getNavigationHistory`` / ``Page.navigateToHistoryEntry``.

Агентам не мешаем: менять вкладки человек может, только пока смотрит стол с телефона (``deskmobile.MOBILE`` — то же
сердцебиение, что у мобильного вида). Вкладка агента — догадка, а не знание: Playwright MCP подключается к Chrome по
CDP и держит подключения ко всем вкладкам (как и наш мобильный вид), поэтому «чья вкладка» из DevTools не видно.
Отмечаем последнюю вкладку, которая сама сменила адрес, открылась или стала активной без действий человека в панели
(касание стола, ввод, кнопки вкладок — последние ``HUMAN_GRACE`` секунд), и не дольше ``AGENT_TTL``.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request

from gas_pult import deskmobile, wsock
from gas_pult.deskmobile import CDP, CdpError, Conn

THUMB = 360                      # ширина миниатюры, точек (карточка ~170 px × 2 на телефоне)
SHOT_TTL = 8.0                   # миниатюра свежа столько секунд
HUMAN_GRACE = 15.0               # перемены в эти секунды после действия человека — его, а не агента
AGENT_TTL = 600.0                # значок «агент» держится столько секунд после последней перемены
TOP_MAX = 400                    # верх страницы в картинке стола — правдоподобные пределы (точки экрана)
ICON_MAX = 20000                 # data:-значок длиннее — не берём
TID = re.compile(r"[A-Za-z0-9_-]{1,64}")
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
HOSTPORT = re.compile(r"^[\w.-]+:\d{1,5}(?:[/?#]|$)")


def norm_url(url: str) -> str:
    """Адрес из строки адреса: только http(s); без схемы — https://. file:, javascript:, chrome:, data: — нет."""
    u = str(url or "").strip()
    if not u or len(u) > 4096 or re.search(r"[\s\x00-\x1f\x7f]", u):
        raise ValueError("введите адрес сайта, например example.com")
    if not re.match(r"^https?://", u, re.I):
        if SCHEME.match(u) and not HOSTPORT.match(u):
            raise ValueError("открыть можно только адрес http:// или https://")
        u = "https://" + u.lstrip("/")
    p = urllib.parse.urlparse(u)
    if p.scheme.lower() not in ("http", "https") or not p.hostname:
        raise ValueError("открыть можно только адрес http:// или https://")
    return u


def host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").removeprefix("www.")
    except ValueError:
        return ""


class Tabs:
    """Вкладки Chrome стола для панели. Один объект на панель; ``connect`` и часы подменяются в тестах."""

    def __init__(self, cdp: str = CDP, connect=Conn, mobile=None, clock=time.monotonic):
        self.cdp, self.connect, self.clock = cdp, connect, clock
        self.mobile = mobile                       # None — deskmobile.MOBILE (на момент вызова: тесты подменяют)
        self.lock = threading.Lock()
        self.shots: dict[str, tuple[float, dict]] = {}
        self.seen: dict[str, str] | None = None    # id → адрес на прошлом опросе (None — опроса ещё не было)
        self.top_id = ""                           # активная вкладка на прошлом опросе
        self.human: dict[str, float] = {}          # id → когда человек менял эту вкладку
        self.human_all = -1e9                      # когда человек трогал стол или вкладки вообще
        self.agent: tuple[str, float] = ("", -1e9)

    # --- DevTools ---
    def http(self, path: str, method: str = "GET"):
        req = urllib.request.Request(self.cdp + path, method=method)
        try:
            with urllib.request.urlopen(req, timeout=4) as r:
                body = r.read()
        except OSError as e:
            raise ValueError(f"браузер рабочего стола не ответил (порт 9222): {e}") from e
        try:
            return json.loads(body or b"null")
        except ValueError:
            return body.decode("utf-8", "replace")

    def pages(self) -> list[dict]:
        d = self.http("/json")
        return [t for t in d if isinstance(t, dict) and t.get("type") == "page" and TID.fullmatch(str(t.get("id")))] \
            if isinstance(d, list) else []

    def page(self, tid: str, pages: list[dict] | None = None) -> dict:
        if not TID.fullmatch(str(tid or "")):
            raise ValueError("нет такой вкладки")
        t = next((p for p in (pages if pages is not None else self.pages()) if p["id"] == tid), None)
        if not t:
            raise ValueError("вкладка уже закрыта")
        return t

    def conn(self, t: dict):
        ws = str(t.get("webSocketDebuggerUrl") or "")
        if not ws:
            raise ValueError("вкладка не отвечает (к ней подключён DevTools)")
        return self.connect(ws)

    # --- кто менял вкладки ---
    def touched(self, tid: str = "", now: float | None = None):
        now = self.clock() if now is None else now
        with self.lock:
            self.human_all = now
            if tid:
                self.human[tid] = now

    def observe(self, pages: list[dict], now: float):
        """Сравнить с прошлым опросом: новая вкладка, смена адреса или активной вкладки без человека — агент."""
        with self.lock:
            cur = {p["id"]: str(p.get("url") or "") for p in pages}
            first, seen = self.seen is None, self.seen or {}
            changed = [] if first else [tid for tid, u in cur.items() if seen.get(tid) != u]
            top = pages[0]["id"] if pages else ""
            if not first and top and top != self.top_id:
                changed.append(top)
            quiet = now - self.human_all > HUMAN_GRACE
            for tid in changed:
                if quiet and now - self.human.get(tid, -1e9) > HUMAN_GRACE:
                    self.agent = (tid, now)
            self.seen, self.top_id = cur, top
            for tid in [k for k in self.human if k not in cur]:
                self.human.pop(tid, None)
            for tid in [k for k in self.shots if k not in cur]:
                self.shots.pop(tid, None)
            aid, at = self.agent
            return aid if aid in cur and now - at <= AGENT_TTL else ""

    # --- для панели ---
    def list(self, idle=None) -> dict:
        """Вкладки (от активной к давней) и сведения об активной: адрес, «Назад/Вперёд», верх страницы на столе.
        ``idle`` — сколько секунд назад человек последний раз трогал стол в панели (касание, ввод)."""
        now = self.clock()
        try:
            idle = float(idle)
        except (TypeError, ValueError):
            idle = None
        if idle is not None and 0 <= idle < HUMAN_GRACE:
            self.touched(now=now - idle)
        pages = self.pages()
        aid = self.observe(pages, now)
        out = {"tabs": [{"id": p["id"], "title": str(p.get("title") or "")[:300], "url": str(p.get("url") or "")[:2000],
                         "host": host(str(p.get("url") or "")), "icon": self.icon(p), "active": i == 0,
                         "agent": p["id"] == aid} for i, p in enumerate(pages)],
               "active": pages[0]["id"] if pages else "", "back": False, "fwd": False, "top": 0}
        if pages:
            try:
                c = self.conn(pages[0])
                try:
                    out["top"] = self.page_top(c)
                    h = c.call("Page.getNavigationHistory")
                    i, n = int(h.get("currentIndex", 0)), len(h.get("entries") or [])
                    out["back"], out["fwd"] = i > 0, i < n - 1
                finally:
                    c.close()
            except (OSError, ValueError, KeyError, TypeError, wsock.Closed):
                pass                                    # без обрезки и стрелок — список всё равно нужен
        return out

    @staticmethod
    def icon(p: dict) -> str:
        f = str(p.get("faviconUrl") or "")
        return f if f.startswith("data:image/") and len(f) <= ICON_MAX else ""

    @staticmethod
    def page_top(c) -> int:
        """Где начинается страница в картинке стола (точки экрана от верха): окно Chrome минус область страницы."""
        b = (c.call("Browser.getWindowForTarget").get("bounds") or {})
        m = c.call("Page.getLayoutMetrics")
        v = m.get("cssVisualViewport") or {}
        h = float(v.get("clientHeight") or 0) * float(v.get("zoom") or 1) * float(v.get("scale") or 1)
        if not h:
            h = float((m.get("visualViewport") or {}).get("clientHeight") or 0)
        top = float(b.get("top") or 0) + float(b.get("height") or 0) - h
        return round(top) if h and 0 <= top <= TOP_MAX else 0

    def shot(self, tid: str) -> dict:
        """Миниатюра вкладки: JPEG ``data:``-адресом, кэш ``SHOT_TTL`` секунд."""
        now = self.clock()
        with self.lock:
            hit = self.shots.get(str(tid))
        if hit and now - hit[0] < SHOT_TTL:
            return hit[1]
        t = self.page(tid)
        c = self.conn(t)
        try:
            v = c.call("Page.getLayoutMetrics").get("cssVisualViewport") or {}
            w = max(1.0, float(v.get("clientWidth") or 1))
            h = min(float(v.get("clientHeight") or w), w * 1.6)
            d = c.call("Page.captureScreenshot", format="jpeg", quality=45, fromSurface=True,
                       clip={"x": float(v.get("pageX") or 0), "y": float(v.get("pageY") or 0), "width": w,
                             "height": h, "scale": min(1.0, THUMB / w)})
        finally:
            c.close()
        data = str(d.get("data") or "")
        if not re.fullmatch(r"[A-Za-z0-9+/=]*", data):
            data = ""
        out = {"id": t["id"], "img": "data:image/jpeg;base64," + data if data else "", "w": round(w), "h": round(h)}
        with self.lock:
            self.shots[t["id"]] = (now, out)
        return out

    def watching(self) -> bool:
        m = self.mobile if self.mobile is not None else deskmobile.MOBILE
        return bool(m.alive())

    def act(self, op: str, tid: str = "", url: str = "") -> dict:
        """Действие человека: open (сделать активной), close, new, go (адрес), back, forward."""
        op = str(op or "")
        if op not in ("open", "close", "new", "go", "back", "forward"):
            raise ValueError("неизвестное действие с вкладкой")
        if not self.watching():
            raise ValueError("вкладки меняются, только пока стол открыт на телефоне — откройте «Браузер» снова")
        if op == "go":
            url = norm_url(url)                         # проверить до любых обращений к Chrome
        pages = self.pages()
        if op == "new":
            target = norm_url(url) if url else "about:blank"
            d = self.http("/json/new?" + urllib.parse.quote(target, safe=":/?#[]@!$&'()*+,;=%-._~"), method="PUT")
            nid = str((d or {}).get("id") or "") if isinstance(d, dict) else ""
            if nid and TID.fullmatch(nid):
                self.http("/json/activate/" + nid)
            self.touched(nid)
            return {"ok": True, "id": nid}
        t = self.page(tid or (pages[0]["id"] if pages else ""), pages)
        self.touched(t["id"])
        if op == "open":
            self.http("/json/activate/" + t["id"])
            return {"ok": True, "id": t["id"]}
        if op == "close":
            nid = ""
            if len(pages) == 1:                         # последняя вкладка: Chrome закрыл бы окно — сперва пустая
                d = self.http("/json/new?about:blank", method="PUT")
                nid = str((d or {}).get("id") or "") if isinstance(d, dict) else ""
            self.http("/json/close/" + t["id"])
            with self.lock:
                self.shots.pop(t["id"], None)
            return {"ok": True, "id": t["id"], "new": nid}
        c = self.conn(t)
        try:
            if op == "go":
                r = c.call("Page.navigate", url=url)
                if r.get("errorText"):
                    raise ValueError(f"не открылось: {r['errorText']}")
                return {"ok": True, "id": t["id"], "url": url}
            h = c.call("Page.getNavigationHistory")
            i, e = int(h.get("currentIndex", 0)), h.get("entries") or []
            j = i - 1 if op == "back" else i + 1
            if not 0 <= j < len(e):
                return {"ok": False, "id": t["id"]}
            c.call("Page.navigateToHistoryEntry", entryId=e[j]["id"])
            return {"ok": True, "id": t["id"], "url": str(e[j].get("url") or "")}
        except CdpError as e:
            raise ValueError(str(e)) from e
        finally:
            c.close()


TABS = Tabs()
