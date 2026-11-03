"""Одноразовые приглашения тестировщиков (задача 31): ссылка ``/invite/<код>`` на 24 часа.

Приглашение привязано к демо-пространству и роли. Человек открывает ссылку → экран входа панели с пометкой
«приглашение в …» → «Войти через Telegram» → в боте «Start» → доступ выдаётся сразу (без кнопки владельца), владельцу
приходит уведомление. Код работает один раз; хранится только его хеш (``invites.json``, 0600). Отзыв —
``gas-pult invite revoke <код>`` (или первые знаки кода из ``gas-pult invite list``).
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from pathlib import Path

from gas_pult import tenants
from gas_pult.config import data_dir, write_private

TTL = 24 * 3600
ROLES = ("member", "viewer")
CODE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
HINT = 6                                     # первые знаки кода — чтобы узнать приглашение в списке и отозвать
_lock = threading.Lock()


def store() -> Path:
    return data_dir() / "invites.json"


def _h(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _load() -> dict:
    try:
        d = json.loads(store().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d: dict):
    write_private(store(), json.dumps(d, ensure_ascii=False))


def state(rec: dict, now: float | None = None) -> str:
    now = time.time() if now is None else now
    if rec.get("revoked"):
        return "revoked"
    if rec.get("used"):
        return "used"
    return "expired" if now >= rec.get("exp", 0) else "active"


def create(tenant: str, role: str = "member", ttl: int = TTL, by: int | None = None) -> str:
    """Новое приглашение; возвращает код (показывается один раз — в файле только хеш)."""
    tenant = tenants.check_slug(tenant)
    if role not in ROLES:
        raise ValueError("роль: member (участник) или viewer (наблюдатель)")
    code, now = secrets.token_urlsafe(18), time.time()
    with _lock:
        d = {k: v for k, v in _load().items() if now - v.get("exp", 0) < 30 * 86400}   # месяц после срока — чистим
        d[_h(code)] = {"tenant": tenant, "role": role, "created": int(now), "exp": int(now + ttl),
                       "hint": code[:HINT], "used": None, "revoked": False, **({"by": int(by)} if by else {})}
        _save(d)
    return code


def check(code: str) -> dict | None:
    """Действующее приглашение (не использовано, не отозвано, срок не вышел) или None."""
    if not CODE.match(str(code or "")):
        return None
    rec = _load().get(_h(code))
    return rec if rec and state(rec) == "active" else None


def redeem(code: str, uid: int) -> dict | None:
    """Использовать приглашение (один раз): запись помечается, возвращается {tenant, role}; иначе None."""
    if not CODE.match(str(code or "")):
        return None
    with _lock:
        d = _load()
        rec = d.get(_h(code))
        if not rec or state(rec) != "active":
            return None
        rec.update(used=int(uid), used_at=int(time.time()))
        _save(d)
    return {"tenant": rec["tenant"], "role": rec["role"]}


def revoke(code_or_hint: str) -> str:
    """Отозвать по коду или по первым знакам (из списка). Возвращает первые знаки отозванного."""
    x = str(code_or_hint or "").strip()
    if len(x) < HINT:
        raise ValueError(f"укажите код или хотя бы {HINT} первых знаков")
    with _lock:
        d = _load()
        keys = [k for k, v in d.items() if k == _h(x) or v.get("hint") == x[:HINT]]
        if len(keys) != 1:
            raise ValueError("такого приглашения нет" if not keys else "несколько совпадений — укажите код целиком")
        d[keys[0]]["revoked"] = True
        _save(d)
        return d[keys[0]]["hint"]


def listing() -> list[dict]:
    now = time.time()
    return sorted(({"hint": v.get("hint", ""), "tenant": v.get("tenant", ""), "role": v.get("role", ""),
                    "state": state(v, now), "exp": v.get("exp", 0), "used": v.get("used")}
                   for v in _load().values()), key=lambda x: -x["exp"])
