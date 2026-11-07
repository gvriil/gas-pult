"""Режим «Фокус» (задача 41): одна сессия — на любом устройстве, по подписанной ссылке, без входа в пульт.

Владелец в меню сессии выпускает «Фокус-ссылку» ``https://<панель>/#focus=<токен>``. Токен — в части адреса после
«#»: браузер не отправляет её на сервер, поэтому ссылка не попадает ни в журнал прокси, ни в Referer. Страница сама
отдаёт токен запросом ``POST /api/focus/open`` — **первое открытие привязывает устройство**: сервер выдаёт cookie
``gp_focus`` (HttpOnly, Secure, SameSite=Strict), и дальше ссылка работает только на этом устройстве.

Что можно с cookie фокуса — только чат одной сессии (``webapp.FOCUS_GET``/``FOCUS_POST``, окно ``w`` — только своё);
всё остальное API отвечает 403. Ссылка гаснет, когда: сессию завершили (из фокуса, из панели, из бота — окно пропало),
владелец нажал «Отозвать» («Настройки» → «Фокус-ссылки»), вышел срок (по умолчанию 7 дней). На сервере — только
SHA-256 от токена и секрета устройства (``focus.json``, 0600).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path

from gas_pult.config import write_private

TTL = 7 * 86400                         # не дольше недели, даже если сессию не завершили
COOKIE = "gp_focus"
HEADER = "X-Gp-Focus"                   # запрос страницы в режиме фокуса: проверяется только cookie фокуса
KEEP = 30 * 86400                       # погасшие записи — месяц для списка, потом чистим
TOKEN_LEN = (24, 64)
GRACE = 30                              # с: окна сессии нет — столько считаем, что её перезапускают


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class Gone(Exception):
    """Ссылка больше не действует: текст — для экрана «Сессия завершена»."""


class Wait(Exception):
    """Окна сессии сейчас нет, но ссылку не гасим: сессию, похоже, перезапускают — ответ 503, страница подождёт."""


class Focus:
    def __init__(self, store: Path):
        self.store, self.lock = store, threading.Lock()

    def _load(self) -> dict:
        try:
            d = json.loads(self.store.read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, d: dict):
        write_private(self.store, json.dumps(d, ensure_ascii=False))

    @staticmethod
    def live(rec: dict, now: float | None = None) -> bool:
        return rec.get("state") == "active" and (time.time() if now is None else now) < rec.get("exp", 0)

    def new(self, w: dict, by: int | None, ttl: int = TTL) -> dict:
        """Новая ссылка на окно ``w`` (из ``tmux.window``): {token, id, exp}. Токен показывается один раз."""
        token, rid, now = secrets.token_urlsafe(32), secrets.token_hex(6), time.time()
        with self.lock:
            d = {k: v for k, v in self._load().items() if self.live(v, now) or now - v.get("ended", now) < KEEP}
            d[rid] = {"h": _h(token), "w": w["id"], "path": w.get("path", ""), "name": w.get("name", ""),
                      "space": w.get("space") or None, "by": by, "created": int(now), "exp": int(now + ttl),
                      "dev": None, "device": "", "opened": None, "state": "active"}
            self._save(d)
        return {"token": token, "id": rid, "exp": int(now + ttl)}

    def _by_token(self, d: dict, token: str) -> str | None:
        token = str(token or "")
        if not TOKEN_LEN[0] <= len(token) <= TOKEN_LEN[1]:
            return None
        h = _h(token)
        return next((k for k, v in d.items() if hmac.compare_digest(v.get("h", ""), h)), None)

    def check_token(self, token: str) -> dict | None:
        """Действующая ссылка по токену (для «Отправить себе», QR): запись или None."""
        d = self._load()
        k = self._by_token(d, token)
        return {**d[k], "id": k} if k and self.live(d[k]) else None

    def open(self, token: str, cookie: str, device: str = "") -> tuple[str, dict]:
        """Открыть ссылку: первое открытие привязывает устройство — (значение cookie, запись). Уже привязана — только
        к тому же устройству (cookie совпадает). Иначе ``Gone`` с объяснением."""
        with self.lock:
            d = self._load()
            k = self._by_token(d, token)
            if not k:
                raise Gone("Ссылка неверна или устарела — попросите новую.")
            rec = d[k]
            if not self.live(rec):
                raise Gone(self.why(rec))
            if rec.get("dev"):
                if self._match(k, rec, cookie):
                    return cookie, {**rec, "id": k}
                raise Gone("Эта ссылка уже открыта на другом устройстве. Попросите новую фокус-ссылку.")
            secret = secrets.token_urlsafe(32)
            rec.update(dev=_h(secret), device=device[:60], opened=int(time.time()))
            self._save(d)
            return f"{k}.{secret}", {**rec, "id": k}

    @staticmethod
    def _match(k: str, rec: dict, cookie: str) -> bool:
        rid, _, secret = str(cookie or "").partition(".")
        return bool(secret) and rid == k and bool(rec.get("dev")) and hmac.compare_digest(rec["dev"], _h(secret))

    def by_cookie(self, cookie: str) -> dict:
        """Запись по cookie устройства: действующая — {..., id}; погасла — ``Gone``; cookie чужой или нет — ``Gone``."""
        rid = str(cookie or "").partition(".")[0]
        rec = self._load().get(rid) if rid else None
        if not rec or not self._match(rid, rec, cookie):
            raise Gone("Фокус-ссылка не открыта на этом устройстве. Откройте ссылку ещё раз.")
        if not self.live(rec):
            raise Gone(self.why(rec))
        return {**rec, "id": rid}

    @staticmethod
    def why(rec: dict) -> str:
        if rec.get("state") == "closed":
            return "Сессия завершена."
        if rec.get("state") == "revoked":
            return "Владелец отозвал эту фокус-ссылку."
        return "Срок фокус-ссылки вышел — попросите новую."

    def end(self, rid: str, state: str = "closed") -> bool:
        with self.lock:
            d = self._load()
            rec = d.get(rid)
            if not rec or not self.live(rec):
                return False
            rec.update(state=state, ended=int(time.time()))
            self._save(d)
            return True

    def end_window(self, wid: str) -> int:
        """Сессию завершили — гасим все её ссылки сразу."""
        with self.lock:
            d, n = self._load(), 0
            for rec in d.values():
                if rec.get("w") == wid and self.live(rec):
                    rec.update(state="closed", ended=int(time.time()))
                    n += 1
            if n:
                self._save(d)
            return n

    def move(self, old: str, new: str) -> int:
        """Сессию перезапустили (модель, поставщик) — окно новое, разговор тот же: ссылки переходят на него."""
        with self.lock:
            d, n = self._load(), 0
            for rec in d.values():
                if rec.get("w") == old and self.live(rec):
                    rec["w"] = new
                    n += 1
            if n:
                self._save(d)
            return n

    def revoke(self, rid: str) -> bool:
        return self.end(str(rid or ""), "revoked")

    def listing(self) -> list[dict]:
        """Действующие ссылки для «Настройки» → «Фокус-ссылки»: без токенов и секретов."""
        now = time.time()
        out = [{"id": k, "name": v.get("name", ""), "space": v.get("space"), "created": v.get("created"),
                "exp": v.get("exp"), "opened": v.get("opened"), "device": v.get("device", "")}
               for k, v in self._load().items() if self.live(v, now)]
        return sorted(out, key=lambda x: -(x["created"] or 0))
