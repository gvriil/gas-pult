"""Вход в панель из обычного браузера: одноразовый код приходит владельцу в Telegram.

1. Браузер просит код (``start``) → бот присылает владельцам 6 цифр, код живёт 5 минут.
2. Человек вводит код (``verify``) → браузер получает cookie-сессию на 30 дней (HttpOnly, Secure, SameSite=Strict).
На сервере хранится только SHA-256 от кода и от сессии. Попыток ввода — 5 на код, запросов кода — 5 за 10 минут.
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
            token = secrets.token_urlsafe(32)
            d = {k: v for k, v in self._load().items() if v["exp"] > time.time()}
            d[_h(token)] = {"exp": time.time() + SESSION_TTL, "ua": ua[:120], "created": time.time()}
            self._save(d)
        return token

    def check(self, token: str) -> bool:
        if not token:
            return False
        s = self._load().get(_h(token))
        return bool(s and s["exp"] > time.time())

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
