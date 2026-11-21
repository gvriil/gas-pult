"""Мобильный вид сайтов в «Браузере» (рабочий стол агентов), пока владелец смотрит стол с телефона.

Владелец 21.11: «когда экран маленький … адаптивность как у мобильных браузеров Safari или DuckDuckGo». Chrome на
столе — настольный: сайт видит окно 500 px и Linux, а не телефон. Через DevTools (CDP, ``127.0.0.1:9222``) каждой
вкладке ставим мобильную эмуляцию: ``Emulation.setDeviceMetricsOverride`` (размер окна, ``mobile``),
``Emulation.setUserAgentOverride`` (Chrome на Android) и ``Emulation.setTouchEmulationEnabled``.

Эмуляция живёт ровно столько, сколько открыто наше подключение к вкладке: закрыли — Chrome сам её снимает (проверено
на живом Chrome 21.11). Поэтому «выключить» = закрыть подключения, а сбой панели или обрыв сети эмуляцию не
оставят. Панель повторяет ``POST /api/desktop/mobile {on: true}`` раз в ~20 с; нет повтора ``TTL`` секунд или пришло
``on: false`` — подключения закрываются. Новые вкладки (агент открыл сайт) — опрос ``/json`` раз в ``POLL`` секунд.

Только стандартная библиотека; WebSocket-клиент — кадры из ``wsock``. Сбой CDP не роняет панель: вкладку пропускаем,
в следующий опрос пробуем снова.
"""

from __future__ import annotations

import base64
import json
import os
import re
import socket
import threading
import time
import urllib.parse
import urllib.request

from gas_pult import wsock

CDP = "http://127.0.0.1:9222"
TTL = 60                                 # без сердцебиения панели столько секунд — выключить
POLL = 2.5                               # опрос новых вкладок
UA = ("Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{v}.0.0.0 "
      "Mobile Safari/537.36")            # сокращённый UA Chrome на Android (как у настоящих телефонов)


class CdpError(OSError):
    pass


class Conn:
    """Подключение DevTools к одной вкладке: WebSocket-клиент (кадры маскируем, ответы сервера — без маски)."""

    def __init__(self, ws_url: str, timeout: float = 5):
        u = urllib.parse.urlparse(ws_url)
        if u.scheme != "ws" or u.hostname not in ("127.0.0.1", "localhost"):
            raise CdpError("только локальный DevTools")
        self.sock = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {u.path or '/'} HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
                          .encode())
        self.rfile = self.sock.makefile("rb")
        line = self.rfile.readline()
        if b" 101 " not in line:
            self.close()
            raise CdpError(f"DevTools не принял подключение: {line[:60]!r}")
        while self.rfile.readline() not in (b"\r\n", b""):
            pass
        self.n = 0

    def call(self, method: str, **params) -> dict:
        """Вызов и ожидание ответа с тем же id (события по пути пропускаем)."""
        self.n += 1
        msg = json.dumps({"id": self.n, "method": method, "params": params}).encode()
        self.sock.sendall(wsock.encode(wsock.TEXT, msg, key=os.urandom(4)))
        while True:
            _, op, data = wsock.read_frame(self.rfile, limit=8 << 20, client=False)
            if op == wsock.CLOSE:
                raise CdpError("DevTools закрыл подключение")
            if op == wsock.PING:
                self.sock.sendall(wsock.encode(wsock.PONG, data, key=os.urandom(4)))
                continue
            if op != wsock.TEXT:
                continue
            d = json.loads(data)
            if d.get("id") == self.n:
                if "error" in d:
                    raise CdpError(f"{method}: {d['error'].get('message', d['error'])}")
                return d.get("result") or {}

    def close(self):
        for f in (lambda: self.sock.sendall(wsock.encode(wsock.CLOSE, b"\x03\xe8", key=os.urandom(4))),
                  self.rfile.close, self.sock.close):
            try:
                f()
            except (OSError, AttributeError):
                pass


def mobile_ua(version_json: dict) -> str:
    """UA Chrome на Android той же версии, что Chrome стола (``/json/version`` → ``Browser: Chrome/157.0…``)."""
    m = re.search(r"Chrome/(\d+)", str(version_json.get("Browser") or ""))
    return UA.format(v=m.group(1) if m else "130")


def clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


class MobileView:
    """Один хозяин на весь Chrome стола: повторный ``set(on=True)`` обновляет параметры, а не плодит подключения."""

    def __init__(self, cdp: str = CDP, ttl: float = TTL, poll: float = POLL, connect=Conn):
        self.cdp, self.ttl, self.poll, self.connect = cdp, ttl, poll, connect
        self.lock = threading.Lock()
        self.conns: dict[str, Conn] = {}         # id вкладки → подключение
        self.applied: dict[str, tuple] = {}      # id вкладки → параметры, с которыми включено
        self.on, self.beat, self.params, self.ua = False, 0.0, (0, 0, 1.0), ""
        self.thread: threading.Thread | None = None
        self.wake = threading.Event()
        self.error = ""

    # --- запрос панели ---
    def set(self, on: bool, w=0, h=0, dpr=1, now: float | None = None) -> dict:
        """Включить (или продлить и обновить параметры) / выключить. Подключения трогает только фоновый поток —
        без гонок между запросами панели; выключение он делает при следующем пробуждении (сразу)."""
        now = time.monotonic() if now is None else now
        with self.lock:
            if on:
                self.params = (int(clamp(w, 0, 4000, 0)), int(clamp(h, 0, 4000, 0)), clamp(dpr, 1, 4, 1.0))
                self.beat = now
            self.on = bool(on)
            if on and (not self.thread or not self.thread.is_alive()):
                self.thread = threading.Thread(target=self.loop, name="desk-mobile", daemon=True)
                self.thread.start()
        self.wake.set()
        return self.status()

    def status(self) -> dict:
        with self.lock:
            return {"on": self.on, "tabs": len(self.conns), "error": self.error}

    # --- фоновый поток: один на всё время работы панели, выключенный — спит без опросов ---
    def alive(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.on and now - self.beat > self.ttl:
                self.on = False                  # панель замолчала (закрыли вкладку, ушла сеть)
            return self.on

    def loop(self):
        while True:
            self.wake.clear()
            if self.alive():
                try:
                    self.sync()
                    self.error = ""
                except (OSError, ValueError, wsock.Closed) as e:   # Chrome перезапускается — попробуем позже
                    self.error = str(e)[:200]
                self.wake.wait(self.poll)
            else:
                self.stop()
                self.wake.wait(self.ttl)

    def tabs(self) -> list[dict]:
        with urllib.request.urlopen(self.cdp + "/json", timeout=3) as r:
            return [t for t in json.loads(r.read() or b"[]")
                    if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]

    def sync(self):
        """Новые вкладки — подключить и включить; закрытые — забыть; параметры сменились — переставить."""
        if not self.ua:
            with urllib.request.urlopen(self.cdp + "/json/version", timeout=3) as r:
                self.ua = mobile_ua(json.loads(r.read() or b"{}"))
        tabs = self.tabs()
        ids = {t["id"] for t in tabs}
        for tid in [k for k in self.conns if k not in ids]:
            self.drop(tid)
        for t in tabs:
            if not self.alive():
                return
            tid, params = t["id"], self.params
            if self.applied.get(tid) == params:
                continue
            try:
                c = self.conns.get(tid)
                if c is None:
                    c = self.connect(t["webSocketDebuggerUrl"])
                    with self.lock:
                        self.conns[tid] = c
                self.apply(c, params)
                self.applied[tid] = params
            except (OSError, ValueError, wsock.Closed) as e:
                self.drop(tid)
                self.error = f"вкладка: {e}"[:200]

    def apply(self, c: Conn, params: tuple):
        w, h, _dpr = params
        # width/height 0 — размер окна Chrome (оно развёрнуто на весь стол); screen — как у телефона. Плотность 0 —
        # своя у Chrome (1): стол передаётся картинкой 1:1, а dpr телефона (3) только заставил бы Chrome рисовать
        # в 9 раз больше точек (проверено 21.11: innerWidth тот же, на экране разницы нет). dpr панели — для журнала.
        screen = {"screenWidth": w, "screenHeight": h} if w and h else {}
        c.call("Emulation.setDeviceMetricsOverride", width=0, height=0, deviceScaleFactor=0, mobile=True, **screen)
        c.call("Emulation.setUserAgentOverride", userAgent=self.ua, platform="Linux armv8l",
               userAgentMetadata={"platform": "Android", "platformVersion": "14", "architecture": "",
                                  "model": "", "mobile": True})
        c.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)

    def drop(self, tid: str):
        with self.lock:
            c = self.conns.pop(tid, None)
            self.applied.pop(tid, None)
        if c:
            c.close()

    def stop(self):
        """Закрыть все подключения — Chrome сам снимает эмуляцию с вкладок."""
        for tid in list(self.conns):
            self.drop(tid)


MOBILE = MobileView()
