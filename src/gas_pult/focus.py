"""Режим «Фокус» (задача 41): одна сессия — на любом устройстве, по подписанной ссылке, без входа в пульт.

Владелец в меню сессии выпускает «Фокус-ссылку» ``https://<панель>/#focus=<токен>``. Токен — в части адреса после
«#»: браузер не отправляет её на сервер, поэтому ссылка не попадает ни в журнал прокси, ни в Referer. Страница сама
отдаёт токен запросом ``POST /api/focus/open`` — **первое открытие привязывает устройство**: сервер выдаёт cookie
``gp_focus`` (HttpOnly, Secure, SameSite=Strict), и дальше ссылка работает только на этом устройстве.

Ссылка на проект (``proj``, меню проекта → «Фокус-ссылка на проект»): все его сессии, «Новая сессия в проекте» и
завершённые чаты — и ничего вне проекта. Закрытие отдельной сессии такую ссылку не гасит.

Что можно с cookie фокуса — только чат одной сессии (``webapp.FOCUS_GET``/``FOCUS_POST``, окно ``w`` — только своё);
всё остальное API отвечает 403. Ссылка гаснет, когда: сессию завершили (из фокуса, из панели, из бота — окно пропало),
владелец нажал «Отозвать» («Настройки» → «Фокус-ссылки»), вышел срок (по умолчанию 7 дней). На сервере — только
SHA-256 от токена и секрета устройства (``focus.json``, 0600).

Демо-ссылка (``mode: "demo"``, меню проекта → «Демо-ссылка»): для показа клиенту и партнёру. Привязки к первому
устройству нет — каждое открытие получает своё cookie на ту же запись (не больше ``DEMO_MAX`` устройств, счётчик
``opens``); права — только смотреть и отвечать на вопрос Claude кнопками (``webapp.DEMO_GET``/``DEMO_POST``).
«Отозвать» гасит все устройства сразу. Старые записи без ``mode`` — обычная ссылка, как раньше.

Ссылка на пространство (``mode: "space"``, GAS-38, владелец 21.11): полная панель одного пространства — как у его
тестировщика (``access.SPACE_OK`` и та же изоляция). Устройство получает «виртуального» человека (``vuid``:
отрицательный номер из id записи), ``People.virtual`` отдаёт ему роль (``member`` — полные права, ``viewer`` —
только чтение) и пространство. Срок — от часа до «без срока», число устройств — ``max`` (0 — без ограничения).
Истекла, отозвана, сверх устройств — ``Gone``, панель покажет «Ссылка не действует».
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
DEMO = "demo"                           # вид ссылки: несколько устройств, только просмотр и выбор вариантов
DEMO_MAX = 20                           # устройств на одну демо-ссылку
# Обычная фокус-ссылка — до трёх устройств одного человека (владелец 20.11: «присылаешь ссылку, открываю — извини»):
# ссылка из Telegram открывается во встроенном браузере, потом — в Safari или Chrome; у них разные cookie.
FOCUS_MAX = 3
SPACE = "space"                         # вид ссылки: панель пространства (GAS-38)
SPACE_TTLS = {"1h": 3600, "1d": 86400, "7d": 7 * 86400, "30d": 30 * 86400, "none": 0}   # 0 — без срока
SPACE_MAX = (1, 3, 0)                   # устройств: 0 — без ограничения
FOREVER = 100 * 365 * 86400             # «без срока» — запись живёт, пока не отзовут
VUID_BASE = 2 ** 50                     # виртуальный человек ссылки: −(VUID_BASE + id записи); не Telegram ID


def vuid(rid: str) -> int:
    """Номер «человека» ссылки на пространство: отрицательный — с Telegram ID не совпадёт."""
    return -(VUID_BASE + int(rid, 16))


def rid_of(uid) -> str | None:
    """Id записи по номеру ``vuid`` или None (обычный человек)."""
    try:
        n = -int(uid) - VUID_BASE
    except (TypeError, ValueError):
        return None
    return f"{n:012x}" if 0 <= n < 16 ** 12 else None


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class Gone(Exception):
    """Ссылка больше не действует: текст — для экрана «Чат завершён»."""


class Denied(Exception):
    """Демо-ссылке это нельзя: ответ ``status`` с кодом ``code`` (403 focus_scope, 409 answered)."""

    def __init__(self, text: str, code: str = "focus_scope", status: int = 403):
        super().__init__(text)
        self.code, self.status = code, status


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

    @staticmethod
    def is_demo(rec: dict) -> bool:
        return rec.get("mode") == DEMO

    def new(self, w: dict, by: int | None, ttl: int = TTL, proj: str | None = None, mode: str = "",
            limit: int = FOCUS_MAX, rights: str = "full", audience: str = "client") -> dict:
        """Новая ссылка на окно ``w`` (из ``tmux.window``): {token, id, exp}. Токен показывается один раз.
        ``proj`` — ссылка на весь проект: ``w`` — {id: "", path, name} проекта, окна у ссылки нет.
        ``mode="demo"`` — демо-ссылка: несколько устройств (``devs``), только просмотр и выбор вариантов.
        ``mode="space"`` — панель пространства ``w["space"]``: ``ttl=0`` — без срока, ``limit`` устройств (0 — сколько
        угодно), ``rights`` «full» или «read»."""
        token, rid, now = secrets.token_urlsafe(32), secrets.token_hex(6), time.time()
        forever = mode == SPACE and not ttl
        ttl = FOREVER if forever else ttl
        with self.lock:
            d = {k: v for k, v in self._load().items() if self.live(v, now) or now - v.get("ended", now) < KEEP}
            d[rid] = {"h": _h(token), "w": w["id"], "path": w.get("path", ""), "name": w.get("name", ""),
                      **({"proj": proj} if proj else {}),
                      **({"mode": DEMO, "devs": {}, "opens": 0} if mode == DEMO else {}),
                      **({"mode": SPACE, "devs": {}, "max": int(limit), "forever": forever,
                          "rights": "read" if rights == "read" else "full",
                          # для кого (штаб 21.11): «client» — человек сам соглашается с условиями строкой при первом
                          # действии; «self» — владелец или его тестировщик, условия отмечены выпуском ссылки
                          "aud": "self" if audience == "self" else "client"} if mode == SPACE else {}),
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
            if self.is_demo(rec):
                return self._open_demo(d, k, rec, cookie, device)
            if self._match(k, rec, cookie):
                return cookie, {**rec, "id": k}
            devs = rec.setdefault("devs", {})
            if rec.get("dev") and rec["dev"] not in devs:         # старая запись: одно устройство в поле dev
                devs[rec["dev"]] = {"device": rec.get("device", ""), "opened": rec.get("opened")}
            lim = int(rec.get("max") or 0) if rec.get("mode") == SPACE else FOCUS_MAX
            if lim and len(devs) >= lim:
                raise Gone(f"Ссылку уже открыли на {lim} {'устройстве' if lim == 1 else 'устройствах'}. Попросите "
                           "новую ссылку или отзовите эту: «Настройки» → «Команда и клиенты» → «Фокус-ссылки».")
            secret, now = secrets.token_urlsafe(32), int(time.time())
            devs[_h(secret)] = {"device": device[:60], "opened": now}
            rec.setdefault("dev", _h(secret))                    # первое устройство — как раньше (совместимость)
            rec.update(device=device[:60], opened=now)
            self._save(d)
            return f"{k}.{secret}", {**rec, "id": k}

    def _open_demo(self, d: dict, k: str, rec: dict, cookie: str, device: str) -> tuple[str, dict]:
        """Демо-ссылка: то же устройство — его cookie; новое — своё cookie, пока устройств меньше ``DEMO_MAX``."""
        if self._match(k, rec, cookie):
            return cookie, {**rec, "id": k}
        devs = rec.setdefault("devs", {})
        if len(devs) >= DEMO_MAX:
            raise Gone(f"Демо-ссылку уже открыли на {DEMO_MAX} устройствах — попросите новую.")
        secret, now = secrets.token_urlsafe(32), int(time.time())
        devs[_h(secret)] = {"device": device[:60], "opened": now}
        rec["opens"] = int(rec.get("opens") or 0) + 1
        rec.update(device=device[:60], opened=now)           # последнее открытие — для списка у владельца
        self._save(d)
        return f"{k}.{secret}", {**rec, "id": k}

    @staticmethod
    def _match(k: str, rec: dict, cookie: str) -> bool:
        rid, _, secret = str(cookie or "").partition(".")
        if not secret or rid != k:
            return False
        h = _h(secret)                                  # любое из открывших устройств (демо — до DEMO_MAX, обычная — 3)
        if any(hmac.compare_digest(x, h) for x in (rec.get("devs") or {})):
            return True
        return rec.get("mode") != DEMO and bool(rec.get("dev")) and hmac.compare_digest(rec["dev"], h)

    def by_cookie(self, cookie: str) -> dict:
        """Запись по cookie устройства: действующая — {..., id}; погасла — ``Gone``; cookie чужой или нет — ``Gone``."""
        rid = str(cookie or "").partition(".")[0]
        rec = self._load().get(rid) if rid else None
        if not rec or not self._match(rid, rec, cookie):
            raise Gone("Фокус-ссылка не открыта на этом устройстве. Откройте ссылку ещё раз.")
        if not self.live(rec):
            raise Gone(self.why(rec))
        return {**rec, "id": rid}

    def space_by_cookie(self, cookie: str) -> dict | None:
        """Ссылка на пространство этого устройства: действует — запись; cookie не от неё — None; погасла — ``Gone``."""
        rid = str(cookie or "").partition(".")[0]
        rec = self._load().get(rid) if rid else None
        if not rec or rec.get("mode") != SPACE or not self._match(rid, rec, cookie):
            return None
        if not self.live(rec):
            raise Gone(self.why(rec))
        return {**rec, "id": rid}

    def person(self, uid) -> dict | None:
        """«Человек» ссылки на пространство (``People.virtual``): {role, tenant} пока ссылка жива, иначе None."""
        rid = rid_of(uid)
        rec = self._load().get(rid) if rid else None
        if not rec or rec.get("mode") != SPACE or not self.live(rec) or not rec.get("space"):
            return None
        return {"role": "viewer" if rec.get("rights") == "read" else "member", "tenant": rec["space"]}

    @staticmethod
    def why(rec: dict) -> str:
        if rec.get("state") == "closed":
            return "Проект удалён." if rec.get("proj") else "Чат завершён."
        if rec.get("state") == "revoked":
            return f"Владелец отозвал эту {'демо' if rec.get('mode') == DEMO else 'фокус'}-ссылку."
        if rec.get("mode") == SPACE:
            return "Срок ссылки вышел — попросите новую."
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
                if wid and rec.get("w") == wid and not rec.get("proj") and self.live(rec):
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
                if old and rec.get("w") == old and not rec.get("proj") and self.live(rec):
                    rec["w"] = new
                    n += 1
            if n:
                self._save(d)
            return n

    def set_browser(self, rid: str, on: bool) -> bool:
        """Разрешить (или запретить) фокус-пользователю подключить свой браузер (владелец 17.11)."""
        with self.lock:
            d = self._load()
            rec = d.get(str(rid or ""))
            if not rec or not self.live(rec) or self.is_demo(rec) or rec.get("mode") == SPACE:
                return False
            rec["browser"] = bool(on)
            self._save(d)
            return True

    def browser_ok(self, rid: str) -> bool:
        """Устройство фокус-ссылки ``rid`` может работать: ссылка жива и браузер разрешён."""
        rec = self._load().get(str(rid or ""))
        return bool(rec) and self.live(rec) and bool(rec.get("browser"))

    def revoke(self, rid: str) -> bool:
        return self.end(str(rid or ""), "revoked")

    def listing(self) -> list[dict]:
        """Действующие ссылки для «Настройки» → «Фокус-ссылки»: без токенов и секретов."""
        now = time.time()
        out = [{"id": k, "name": v.get("name", ""), "w": v.get("w"), "space": v.get("space"), "proj": v.get("proj"),
                "created": v.get("created"), "browser": bool(v.get("browser")),
                "exp": v.get("exp"), "opened": v.get("opened"), "device": v.get("device", ""),
                **({"mode": DEMO, "devices": len(v.get("devs") or {}), "opens": v.get("opens", 0)}
                   if v.get("mode") == DEMO else {}),
                **({"mode": SPACE, "devices": len(v.get("devs") or {}), "max": v.get("max", 0),
                    "rights": v.get("rights", "full"), "forever": bool(v.get("forever"))}
                   if v.get("mode") == SPACE else {})}
               for k, v in self._load().items() if self.live(v, now)]
        return sorted(out, key=lambda x: -(x["created"] or 0))
