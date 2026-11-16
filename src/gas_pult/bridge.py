"""Мост к браузеру пользователя (решение владельца 16.11, продукт «пульт управляет браузером пользователя»).

На компьютере пользователя (Mac, Windows) работает лёгкий мост ``bridge/gas-pult-bridge.mjs``: он сам подключается к
пульту исходящим защищённым соединением (WebSocket ``/api/bridge/ws``) и локально запускает Playwright MCP в режиме
``--extension`` — управление уже открытым Chrome/Edge пользователя, где он вошёл в свои сервисы. Агенты в окнах
пульта видят этот браузер как MCP-сервер ``gas-pult bridge-mcp`` («browser-local») — с телефона и с компьютера.

- Пара: владелец в панели получает одноразовый код (10 мин) → мост меняет его на токен устройства (в файле — только
  хэш, 0600). Устройства — список в настройках, любое можно отозвать.
- Токен моста — в подпротоколе WebSocket (``gpb-<токен>``): своих заголовков WebSocket не умеет.
- ``/api/bridge/rpc`` — только локальным процессам пульта: секрет из файла 0600 (снаружи запросы тоже приходят с
  127.0.0.1 через Caddy, поэтому адрес — не проверка).
- Банки и госуслуги — запрет по умолчанию (``BLOCKED``), разрешает пользователь у себя в мосте; сервер тоже не
  пропускает переход на них, пока устройство не сообщило, что пользователь их разрешил.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from pathlib import Path

PAIR_TTL = 600
RPC_TIMEOUT = 120.0
BLOCKED = ("gosuslugi.ru", "nalog.gov.ru", "nalog.ru", "pfr.gov.ru", "sfr.gov.ru", "mos.ru", "sberbank.ru",
           "sber.ru", "tbank.ru", "tinkoff.ru", "vtb.ru", "alfabank.ru", "raiffeisen.ru", "gazprombank.ru",
           "psbank.ru", "open.ru", "rshb.ru", "pochtabank.ru", "sovcombank.ru", "mkb.ru", "paypal.com",
           "revolut.com", "wise.com", "bunq.com", "n26.com")
_CODE = re.compile(r"^[A-Z0-9]{8}$")


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def blocked_host(url: str, allowed: list[str] | tuple = ()) -> str:
    """Домен из запретного списка (банк, госуслуги), если пользователь его не разрешил; иначе ""."""
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/:?#]+)", str(url or "").strip().lower())
    host = m.group(1) if m else ""
    for d in BLOCKED:
        if (host == d or host.endswith("." + d)) and d not in allowed:
            return d
    return ""


class Devices:
    """Устройства с мостом и одноразовые коды пары. Файл ``bridge_devices.json`` (0600): id, имя, ОС, хэш токена."""

    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock, self.lock = Path(path), clock, threading.Lock()
        self.codes: dict[str, float] = {}

    def _load(self) -> list[dict]:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return [x for x in d if isinstance(x, dict) and x.get("id")] if isinstance(d, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, items: list[dict]):
        from gas_pult.config import write_private
        write_private(self.path, json.dumps(items, ensure_ascii=False))

    def pair_code(self) -> dict:
        now = self.clock()
        with self.lock:
            self.codes = {c: t for c, t in self.codes.items() if t > now}
            code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
            self.codes[code] = now + PAIR_TTL
        return {"code": code, "expires": int(now + PAIR_TTL)}

    def claim(self, code: str, name: str, os_name: str) -> dict:
        code = str(code or "").strip().upper()
        now = self.clock()
        with self.lock:
            if not _CODE.match(code) or self.codes.pop(code, 0) < now:
                raise PermissionError("код неверный или устарел — получите новый в панели")
            token = secrets.token_urlsafe(32)
            dev = {"id": secrets.token_hex(4), "name": " ".join(str(name or "компьютер").split())[:60],
                   "os": str(os_name or "")[:20], "token": _h(token), "created": now, "seen": now}
            items = self._load()
            items.append(dev)
            self._save(items)
        return {"id": dev["id"], "token": token}

    def check(self, token: str) -> dict | None:
        if not token:
            return None
        h = _h(token)
        return next((d for d in self._load() if secrets.compare_digest(d.get("token", ""), h)), None)

    def seen(self, did: str):
        with self.lock:
            items = self._load()
            for d in items:
                if d["id"] == did:
                    d["seen"] = self.clock()
            self._save(items)

    def listing(self) -> list[dict]:
        return [{k: d.get(k) for k in ("id", "name", "os", "created", "seen")} for d in self._load()]

    def revoke(self, did: str) -> bool:
        with self.lock:
            items = self._load()
            keep = [d for d in items if d["id"] != did]
            if len(keep) == len(items):
                return False
            self._save(keep)
        return True


class Hub:
    """Подключённые мосты и их ответы: запрос агента (JSON-RPC) → мост → ответ, с подменой id (несколько агентов)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.conns: dict[str, dict] = {}              # id устройства → {"ws", "allowed": [домены]}
        self.wait: dict[str, tuple[threading.Event, list]] = {}

    def attach(self, did: str, ws) -> None:
        with self.lock:
            old = self.conns.get(did)
            self.conns[did] = {"ws": ws, "allowed": []}
        if old:
            try:
                old["ws"].close(4000, "заменено новым подключением")
            except Exception:
                pass

    def detach(self, did: str, ws) -> None:
        with self.lock:
            if self.conns.get(did, {}).get("ws") is ws:
                del self.conns[did]

    def online(self) -> list[str]:
        with self.lock:
            return list(self.conns)

    def on_message(self, did: str, text: str) -> None:
        """Сообщение от моста: ответ на запрос (по нашему id) или служебное (``{"allowed": [...]}``)."""
        try:
            m = json.loads(text)
        except ValueError:
            return
        if isinstance(m, dict) and "bridge" in m:     # мост сообщает настройки пользователя
            with self.lock:
                if did in self.conns:
                    self.conns[did]["allowed"] = [str(x) for x in (m["bridge"].get("allowed") or [])][:50]
            return
        rid = str(m.get("id")) if isinstance(m, dict) else ""
        with self.lock:
            w = self.wait.get(rid)
        if w:
            w[1].append(m)
            w[0].set()

    def call(self, msg: dict, did: str = "", timeout: float = RPC_TIMEOUT) -> dict | None:
        """JSON-RPC от агента → мост; запрос — ждём ответ, уведомление — None."""
        with self.lock:
            did = did or next(iter(self.conns), "")
            c = self.conns.get(did)
        if not c:
            if "id" in msg:
                return {"jsonrpc": "2.0", "id": msg["id"], "error": {
                    "code": -32000, "message": "браузер пользователя не подключён: запустите мост на компьютере "
                                               "(панель → Настройки → Компьютеры)"}}
            return None
        p = msg.get("params") or {}
        nav = msg.get("method") == "tools/call" and (p.get("name") or "").endswith("navigate")
        if nav and (d := blocked_host((p.get("arguments") or {}).get("url", ""), c["allowed"])):
                return {"jsonrpc": "2.0", "id": msg.get("id"), "error": {
                    "code": -32001, "message": f"сайт {d} (банк или госуслуги) выключен: включить его может только "
                                               f"пользователь в мосте на своём компьютере, прочитав правила сервиса"}}
        if "id" not in msg:
            c["ws"].send_text(json.dumps(msg, ensure_ascii=False))
            return None
        rid = "gp-" + secrets.token_hex(6)
        ev, box = threading.Event(), []
        with self.lock:
            self.wait[rid] = (ev, box)
        try:
            c["ws"].send_text(json.dumps({**msg, "id": rid}, ensure_ascii=False))
            if not ev.wait(timeout):
                return {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32002, "message": "мост не ответил"}}
            return {**box[0], "id": msg["id"]}
        finally:
            with self.lock:
                self.wait.pop(rid, None)
