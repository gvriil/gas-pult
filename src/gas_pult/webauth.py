"""Вход в панель из обычного браузера.

**Через Telegram** (основной, ``TgLogins``): браузер получает ссылку ``t.me/<бот>?start=login_<nonce>`` и свой
секретный номер ожидания ``rid``. Человек нажимает «Start» у себя в Telegram — бот видит, *кто* это, спрашивает
«войти?» и отмечает вход. Браузер, опрашивая по ``rid``, получает сессию этого человека. ``nonce`` из ссылки не даёт
войти: опрашивают по ``rid``, который знает только браузер. Ожидающие входы — в файле: их видят и панель, и бот.

**Кодом владельцу** (запасной, ``Auth.start/verify``): 6 цифр приходят владельцам, код живёт 5 минут.

Сессия — cookie на 30 дней (HttpOnly, Secure, SameSite=Strict) с Telegram ID человека; роль проверяется на каждый
запрос (``people.py``). На сервере хранятся только SHA-256 от кодов, номеров ожидания и сессий.

**Подтверждение кодом** (аудит 09.11): сессии моложе ``CONFIRM_FRESH`` выполнять команды на сервере и писать в
терминал (``webapp.CONFIRM``) не могут, пока человек не введёт код (``confirm_start`` / ``confirm_verify``); после
этого сессия помечена «подтверждена» до конца её срока. Код живёт ``CONFIRM_TTL``, 5 попыток, привязан к сессии.
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

CODE_TTL = 300
CODE_TRIES = 5
START_LIMIT = (5, 600)                   # не больше 5 кодов за 10 минут — чтобы бот не засыпали
SESSION_TTL = 30 * 86400
COOKIE = "gp_session"
LOGIN_TTL = 300
LEGACY = -1                              # сессия по коду владельцу (до входа через Telegram): права владельца
CONFIRM_FRESH = 24 * 3600                # сессия моложе суток — команды на сервере только после кода
CONFIRM_TTL = 600


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class Auth:
    def __init__(self, store: Path):
        self.store, self.lock = store, threading.Lock()
        self.codes: dict[str, dict] = {}         # id запроса → {hash, exp, tries}
        self.starts: list[float] = []
        self.cstarts: list[float] = []          # коды подтверждения — свой счётчик: не мешают входу кодом

    def _load(self) -> dict:
        try:
            return json.loads(self.store.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, d: dict):
        write_private(self.store, json.dumps(d))

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

    def _take(self, rid: str, code: str, sess: str | None = None):
        """Проверить код запроса ``rid`` (под замком): верный — запрос гасится, иначе ValueError с остатком попыток.
        ``sess`` — код подтверждения годится только той сессии, для которой его запросили."""
        c = self.codes.get(rid)
        if not c or c["exp"] < time.time() or c.get("sess") != sess:
            raise ValueError("код устарел — запросите новый")
        c["tries"] += 1
        if c["tries"] > CODE_TRIES:
            self.codes.pop(rid, None)
            raise ValueError("слишком много попыток — запросите новый код")
        if not hmac.compare_digest(c["hash"], _h(str(code).strip())):
            raise ValueError(f"неверный код, осталось попыток: {CODE_TRIES - c['tries']}")
        self.codes.pop(rid, None)

    def verify(self, rid: str, code: str, ua: str = "") -> str:
        """Верный код → новая сессия (её значение — в cookie браузера)."""
        with self.lock:
            self._take(rid, code)
        return self.issue(LEGACY, ua)

    def needs_confirm(self, token: str, fresh: int = CONFIRM_FRESH) -> bool:
        """Сессии нужен код перед командами на сервере: она моложе ``fresh`` и ещё не подтверждена. Сессии без
        отметки времени (выданы до неё) считаются старыми."""
        s = self._load().get(_h(token)) if token else None
        if not s or s.get("confirmed") or not s.get("created"):
            return False
        return time.time() - s["created"] < fresh

    def confirm_start(self, token: str) -> tuple[str, str]:
        """Код подтверждения для сессии ``token``: (id запроса — браузеру, код — человеку). Лимит — как у входа."""
        if self.uid(token) is None:
            raise ValueError("нужен вход")
        now = time.time()
        with self.lock:
            self.cstarts = [t for t in self.cstarts if now - t < START_LIMIT[1]]
            if len(self.cstarts) >= START_LIMIT[0]:
                raise ValueError("слишком много запросов кода — подождите 10 минут")
            self.cstarts.append(now)
            self.codes = {k: v for k, v in self.codes.items() if v["exp"] > now}
            rid, code = secrets.token_urlsafe(16), f"{secrets.randbelow(10**6):06d}"
            self.codes[rid] = {"hash": _h(code), "exp": now + CONFIRM_TTL, "tries": 0, "sess": _h(token)}
        return rid, code

    def confirm_verify(self, token: str, rid: str, code: str):
        """Верный код → сессия подтверждена до конца своего срока."""
        with self.lock:
            self._take(str(rid), code, _h(token))
            d = self._load()
            if (s := d.get(_h(token))) is None or s["exp"] < time.time():
                raise ValueError("сессия истекла — войдите снова")
            s["confirmed"] = time.time()
            self._save(d)

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

    def drop(self, uid: int) -> int:
        """Погасить все сессии человека (его отключили или вход перенесён). Возвращает, сколько."""
        with self.lock:
            d = self._load()
            keep = {k: v for k, v in d.items() if v.get("uid", LEGACY) != int(uid)}
            if len(keep) != len(d):
                self._save(keep)
        return len(d) - len(keep)

    def logout(self, token: str):
        with self.lock:
            d = self._load()
            if d.pop(_h(token), None) is not None:
                self._save(d)


def device(ua: str) -> str:
    """Устройство коротко — для «вошёл: имя, устройство, время»: «iPhone · Safari», «Windows · Chrome»."""
    ua = ua or ""
    os_ = next((n for k, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
                               ("Mac OS X", "Mac"), ("Macintosh", "Mac"), ("CrOS", "Chromebook"), ("Linux", "Linux"))
                if k in ua), "")
    br = next((n for k, n in (("YaBrowser", "Яндекс Браузер"), ("Edg/", "Edge"), ("OPR/", "Opera"),
                              ("Firefox/", "Firefox"), ("CriOS", "Chrome"), ("Chrome/", "Chrome"),
                              ("Safari/", "Safari")) if k in ua), "")
    return " · ".join(x for x in (os_, br) if x) or "браузер"


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
        write_private(self.store, json.dumps(d))

    def start(self, ip: str = "", ua: str = "", offer: dict | None = None, invite: str = "",
              link: int | None = None) -> tuple[str, str]:
        """(rid — браузеру для опроса, nonce — в ссылку на бота). ``offer`` — вход с предложения (offers.py): имя
        бизнеса, начало кода, выбранный модуль, страна, версия условий — без ПДн; бот покажет это владельцу.
        ``link`` — гость без Telegram привязывает свой Telegram (``People.adopt``): бот переносит запись."""
        rid, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(12)
        with self.lock:
            d = self._load()
            if len(d) >= 20:
                raise ValueError("слишком много входов сразу — подождите пару минут")
            d[nonce] = {"rid": _h(rid), "exp": time.time() + LOGIN_TTL, "ip": ip[:45], "ua": ua[:120],
                        "uid": None, "state": "wait", **({"offer": offer} if offer else {}),
                        **({"invite": invite} if invite else {}),      # приглашение (invites.py): доступ — сразу
                        **({"link": int(link)} if link is not None else {})}
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
