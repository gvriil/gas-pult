"""Вход в панель из обычного браузера.

**Через Telegram** (основной, ``TgLogins``): браузер получает ссылку ``t.me/<бот>?start=login_<nonce>`` и свой
секретный номер ожидания ``rid``. Человек нажимает «Start» у себя в Telegram — бот видит, *кто* это, спрашивает
«войти?» и отмечает вход. Браузер, опрашивая по ``rid``, получает сессию этого человека. ``nonce`` из ссылки не даёт
войти: опрашивают по ``rid``, который знает только браузер. Ожидающие входы — в файле: их видят и панель, и бот.

**Кодом владельцу** (запасной, ``Auth.start/verify``): 6 цифр приходят владельцам, код живёт 5 минут.

Сессия — cookie на 30 дней (HttpOnly, Secure, SameSite=Strict) с Telegram ID человека; роль проверяется на каждый
запрос (``people.py``). На сервере хранятся только SHA-256 от кодов, номеров ожидания и сессий.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path

CODE_TTL = 300
CODE_TRIES = 5
START_LIMIT = (5, 600)                   # не больше 5 кодов за 10 минут — чтобы бот не засыпали
SESSION_TTL = 30 * 86400
COOKIE = "gp_session"
LOGIN_TTL = 300
LEGACY = -1                              # сессия по коду владельцу (до входа через Telegram): права владельца


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class Auth:
    def __init__(self, store: Path):
        self.store, self.lock = store, threading.Lock()
        self.codes: dict[str, dict] = {}         # id запроса → {hash, exp, tries}
        self.starts: list[float] = []

    def _load(self) -> dict:
        try:
            return json.loads(self.store.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, d: dict):
        self.store.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.store.write_text(json.dumps(d))
        self.store.chmod(0o600)

    def start(self) -> tuple[str, str]:
        """Новый код: (id запроса, код). Код уходит владельцу, id — браузеру."""
        now = time.time()
        with self.lock:
            self.starts = [t for t in self.starts if now - t < START_LIMIT[1]]
            if len(self.starts) >= START_LIMIT[0]:
                raise ValueError("слишком много запросов кода — подождите 10 минут")
            self.starts.append(now)
            self.codes = {k: v for k, v in self.codes.items() if v["exp"] > now}
            rid, code = secrets.token_urlsafe(16), f"{secrets.randbelow(10**6):06d}"
            self.codes[rid] = {"hash": _h(code), "exp": now + CODE_TTL, "tries": 0}
        return rid, code

    def verify(self, rid: str, code: str, ua: str = "") -> str:
        """Верный код → новая сессия (её значение — в cookie браузера)."""
        with self.lock:
            c = self.codes.get(rid)
            if not c or c["exp"] < time.time():
                raise ValueError("код устарел — запросите новый")
            c["tries"] += 1
            if c["tries"] > CODE_TRIES:
                self.codes.pop(rid, None)
                raise ValueError("слишком много попыток — запросите новый код")
            if not hmac.compare_digest(c["hash"], _h(code.strip())):
                raise ValueError(f"неверный код, осталось попыток: {CODE_TRIES - c['tries']}")
            self.codes.pop(rid, None)
        return self.issue(LEGACY, ua)

    def issue(self, uid: int, ua: str = "") -> str:
        """Новая сессия человека ``uid`` (её значение — в cookie браузера)."""
        token = secrets.token_urlsafe(32)
        with self.lock:
            d = {k: v for k, v in self._load().items() if v["exp"] > time.time()}
            d[_h(token)] = {"exp": time.time() + SESSION_TTL, "ua": ua[:120], "created": time.time(), "uid": uid}
            self._save(d)
        return token

    def uid(self, token: str) -> int | None:
        """Чья сессия: Telegram ID, LEGACY (вход кодом владельцу) или None (нет/истекла)."""
        if not token:
            return None
        s = self._load().get(_h(token))
        return s.get("uid", LEGACY) if s and s["exp"] > time.time() else None

    def check(self, token: str) -> bool:
        return self.uid(token) is not None

    def logout(self, token: str):
        with self.lock:
            d = self._load()
            if d.pop(_h(token), None) is not None:
                self._save(d)


def cookie_value(header: str) -> str:
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == COOKIE:
            return v
    return ""


def set_cookie(token: str, max_age: int = SESSION_TTL) -> str:
    return f"{COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; Secure; SameSite=Strict"


class TgLogins:
    """Ожидающие входы «через Telegram» — в файле 0600: панель их создаёт и опрашивает, бот отмечает."""

    def __init__(self, store: Path):
        self.store, self.lock = store, threading.Lock()

    def _load(self) -> dict:
        try:
            d = json.loads(self.store.read_text())
        except (OSError, ValueError):
            return {}
        now = time.time()
        return {k: v for k, v in d.items() if v["exp"] > now}

    def _save(self, d: dict):
        self.store.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = self.store.with_suffix(".tmp")
        tmp.write_text(json.dumps(d))
        tmp.chmod(0o600)
        tmp.replace(self.store)

    def start(self, ip: str = "", ua: str = "") -> tuple[str, str]:
        """(rid — браузеру для опроса, nonce — в ссылку на бота)."""
        rid, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(12)
        with self.lock:
            d = self._load()
            if len(d) >= 20:
                raise ValueError("слишком много входов сразу — подождите пару минут")
            d[nonce] = {"rid": _h(rid), "exp": time.time() + LOGIN_TTL, "ip": ip[:45], "ua": ua[:120],
                        "uid": None, "state": "wait"}
            self._save(d)
        return rid, nonce

    def info(self, nonce: str) -> dict | None:
        """Для бота: откуда входят (адрес, браузер) — только пока вход ждёт решения."""
        e = self._load().get(nonce)
        return e if e and e["state"] == "wait" else None

    def decide(self, nonce: str, uid: int, ok: bool) -> bool:
        with self.lock:
            d = self._load()
            e = d.get(nonce)
            if not e or e["state"] != "wait":
                return False
            e.update(state="ok" if ok else "no", uid=int(uid))
            self._save(d)
        return True

    def poll(self, rid: str) -> tuple[str, int | None]:
        """«wait», («ok», uid) — вход подтверждён (запись гасится), «no» — отказ, «expired» — ссылка устарела."""
        h = _h(rid or "")
        with self.lock:
            d = self._load()
            nonce = next((k for k, v in d.items() if hmac.compare_digest(v["rid"], h)), None)
            if not nonce:
                return "expired", None
            e = d[nonce]
            if e["state"] == "wait":
                return "wait", None
            d.pop(nonce)
            self._save(d)
        return (e["state"], e["uid"]) if e["state"] == "ok" else ("no", None)
