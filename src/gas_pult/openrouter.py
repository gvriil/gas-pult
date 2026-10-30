"""OpenRouter: вход в одно касание (OAuth PKCE), состояние ключа и каталог моделей.

Вход: панель открывает ``openrouter.ai/auth`` с ``code_challenge`` (S256) и ``state``; человек входит в OpenRouter и
нажимает «Authorize»; OpenRouter возвращает браузер на ``<панель>/openrouter/callback?code=…&state=…``; сервер меняет
код на ключ (``POST /api/v1/auth/keys`` с ``code_verifier``) и сохраняет его как обычный ключ (secrets.json, 0600).
Ключ не проходит через браузер. ``state`` одноразовый, живёт 10 минут и выдаётся только владельцу панели —
без него обратный адрес ничего не делает.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

AUTH = "https://openrouter.ai/auth"
EXCHANGE = "https://openrouter.ai/api/v1/auth/keys"
KEY_INFO = "https://openrouter.ai/api/v1/key"
MODELS = "https://openrouter.ai/api/v1/models"
TTL = 600                    # код OpenRouter живёт 10 минут — ссылка входа столько же
CALLBACK = "/openrouter/callback"


def _http(url: str, body: dict | None = None, key: str | None = None) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "gas-pult"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data, headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:200]
        raise ValueError({401: "ключ не подошёл", 403: "код входа неверный или устарел — войдите ещё раз"}
                         .get(e.code, f"ошибка {e.code} {detail}")) from None
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise ValueError(f"OpenRouter недоступен: {e}") from None


def _per_million(v) -> float | None:
    return round(float(v) * 1e6, 2) if v not in (None, "") else None


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


class OpenRouter:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending: dict[str, tuple[str, float]] = {}      # state → (code_verifier, когда выдан)
        self.catalog: tuple[float, list[dict]] = (0, [])

    def start(self, base_url: str) -> str:
        """Ссылка на вход в OpenRouter; после «Authorize» браузер вернётся на ``base_url`` + CALLBACK."""
        verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(24)
        with self.lock:
            now = time.time()
            self.pending = {s: v for s, v in self.pending.items() if now - v[1] < TTL}
            self.pending[state] = (verifier, now)
        return AUTH + "?" + urllib.parse.urlencode({
            "callback_url": base_url.rstrip("/") + CALLBACK, "code_challenge": challenge(verifier),
            "code_challenge_method": "S256", "state": state, "key_label": "gas-pult"})

    def finish(self, code: str, state: str) -> str:
        """Код из обратного адреса → ключ OpenRouter. ``state`` гасится сразу — второй раз не сработает."""
        with self.lock:
            item = self.pending.pop(state, None)
        if not item or time.time() - item[1] > TTL:
            raise ValueError("ссылка входа устарела — нажмите «Войти через OpenRouter» ещё раз")
        if not code:
            raise ValueError("OpenRouter не прислал код — вход отменён?")
        key = _http(EXCHANGE, {"code": code, "code_verifier": item[0], "code_challenge_method": "S256"}).get("key")
        if not key:
            raise ValueError("OpenRouter не выдал ключ — попробуйте ещё раз")
        return key

    @staticmethod
    def info(key: str) -> dict:
        """Состояние ключа: подпись, расход, лимит и остаток (в долларах) — без секретов."""
        d = _http(KEY_INFO, key=key).get("data") or {}
        return {k: d.get(k) for k in ("label", "usage", "usage_monthly", "limit", "limit_remaining", "is_free_tier")}

    def models(self) -> list[dict]:
        """Каталог моделей OpenRouter (публичный, без ключа), кэш на час: id, название, контекст, цена за 1 млн."""
        with self.lock:
            if time.time() - self.catalog[0] < 3600 and self.catalog[1]:
                return self.catalog[1]
        out = []
        for m in _http(MODELS).get("data", []):
            if m.get("id", "").endswith(":batch"):
                continue                                    # пакетные варианты для интерактивной работы не нужны
            price = m.get("pricing") or {}
            out.append({"id": m["id"], "name": m.get("name", m["id"]), "ctx": m.get("context_length"),
                        "in": _per_million(price.get("prompt")), "out": _per_million(price.get("completion"))})
        with self.lock:
            self.catalog = (time.time(), out)
        return out
