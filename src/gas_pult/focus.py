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

Ссылка на протокол встречи (``mode: "meeting"``, владелец 22.11): только один протокол — плеер, оглавление, текст,
«Что сделать» (``access.MEETING_GET``). Окна и сессии у неё нет; протокол — поле ``mt`` записи, не из запроса.
Несколько устройств (участники встречи), не больше ``MEETING_MAX``; срок — 30 дней; «Отозвать» гасит все сразу.

«Открыть на другом устройстве» (владелец 22.11: на телефоне ссылка открылась, на компьютере — «Ссылка не действует»):
страница убирает токен из адреса, и адрес «/?focus» без cookie ничего не открывает. Поэтому открытое устройство (или
владелец) выпускает **дополнительный токен** той же записи (``extra``): на сервере — только SHA-256 и срок, токен
одноразовый, живёт ``EXTRA_TTL`` (15 минут) и не даёт устройств сверх лимита записи (``limit_of``). Ответ «не действует»
несёт причину (``Gone.why``): ``nodevice`` — на этом устройстве ссылку не открывали, ``limit`` — все места заняты,
``expired``/``revoked``/``closed``/``bad`` — по записи. По ней страница показывает свой экран и «Попросить доступ».
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from pathlib import Path

from gas_pult import store as jstore

TTL = 7 * 86400                         # не дольше недели, даже если сессию не завершили
COOKIE = "gp_focus"
HEADER = "X-Gp-Focus"                   # запрос страницы в режиме фокуса: проверяется только cookie фокуса
KEEP = 30 * 86400                       # погасшие записи — месяц для списка, потом чистим
TOKEN_LEN = (24, 64)
CHATS_MAX = 300                         # чатов, начатых по ссылке, в её записи (старые — вытесняются)
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
MEETING = "meeting"                     # вид ссылки: один протокол встречи (meetings.py)
MEETING_MAX = 50                        # устройств на ссылку на протокол: участники встречи
MEETING_TTL = 30 * 86400
EXTRA_TTL = 15 * 60                     # дополнительный токен «Открыть на другом устройстве»: одноразовый, 15 минут
ASKS_KEEP = 86400                       # запросы доступа «Попросить доступ» — сутки, не больше ASKS_MAX
ASKS_MAX = 50
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


# ---------- пишет человек по ссылке (тестировщик 23.11) ----------
# «При каждом запросе сначала предлагает твои данные (твой комп, твою почту)»: Claude в окне владельца видит его
# глобальные правила, его почту (MCP) и его предупреждения сервера — и не знал, что пишет другой человек. Пометка
# пульта в начале ввода: кто пишет и что ресурсы владельца не предлагать. На каждое сообщение (после сжатия контекста
# Claude помнит только свежие). В ленте её нет (``guest_unmark``).
GUEST = re.compile(r"\A\[Пульт: пишет человек по ссылке «[^»\n]*»[^\n]*\]\s*")


def guest_note(name: str) -> str:
    """Пометка для агента (одна строка): кто пишет и правило о ресурсах владельца."""
    name = re.sub(r"[«»\[\]\r\n]+", " ", str(name or "")).strip()[:60] or "без названия"
    return (f"[Пульт: пишет человек по ссылке «{name}», не владелец пульта. Не предлагай ресурсы владельца пульта "
            f"(его почту, компьютер, сервер, аккаунты, Диск) — работай с тем, что даёт этот человек; если нужен "
            f"доступ — спроси его.]")


def guest_unmark(text: str) -> str:
    """Текст для ленты: без пометки пульта — человек её не писал."""
    return GUEST.sub("", text) if text.startswith("[Пульт:") else text


class Gone(Exception):
    """Ссылка больше не действует: текст — для экрана «Чат завершён». ``why`` — причина для своего экрана страницы
    (nodevice, limit, expired, revoked, closed, bad); ``rid`` — запись, если она известна (для «Попросить доступ»)."""

    def __init__(self, text: str, why: str = "", rid: str = ""):
        super().__init__(text)
        self.why, self.rid = why, rid


class Denied(Exception):
    """Демо-ссылке это нельзя: ответ ``status`` с кодом ``code`` (403 focus_scope, 409 answered)."""

    def __init__(self, text: str, code: str = "focus_scope", status: int = 403):
        super().__init__(text)
        self.code, self.status = code, status


class Wait(Exception):
    """Окна сессии сейчас нет, но ссылку не гасим: сессию, похоже, перезапускают — ответ 503, страница подождёт."""


class Focus:
    def __init__(self, store: Path):
        self.store = store

    def mark_guest(self, wid: str, rec: dict, text: str, now: float | None = None) -> str:
        """Ввод агенту от человека по фокус-ссылке ``rec``: пометка ``guest_note`` — на КАЖДОЕ сообщение (штаб 23.11:
        после сжатия контекста Claude забыл бы пометку, поставленную раз в несколько минут). Пометка короткая, в
        ленте её не видно (``guest_unmark``)."""
        return guest_note(rec.get("name", "")) + "\n\n" + text

    def _locked(self):
        """Чтение-изменение-запись focus.json: замок потоков и процессов — бот гасит ссылки, панель их выпускает."""
        return jstore.locked(self.store)

    def _load(self) -> dict:
        return jstore.load(self.store)

    def _save(self, d: dict):
        jstore.save(self.store, d, ensure_ascii=False)

    @staticmethod
    def live(rec: dict, now: float | None = None) -> bool:
        return rec.get("state") == "active" and (time.time() if now is None else now) < rec.get("exp", 0)

    @staticmethod
    def is_demo(rec: dict) -> bool:
        return rec.get("mode") == DEMO

    @staticmethod
    def is_meeting(rec: dict) -> bool:
        return rec.get("mode") == MEETING

    def new(self, w: dict, by: int | None, ttl: int = TTL, proj: str | None = None, mode: str = "",
            limit: int = FOCUS_MAX, rights: str = "full", audience: str = "client", mt: str = "") -> dict:
        """Новая ссылка на окно ``w`` (из ``tmux.window``): {token, id, exp}. Токен показывается один раз.
        ``proj`` — ссылка на весь проект: ``w`` — {id: "", path, name} проекта, окна у ссылки нет.
        ``mode="demo"`` — демо-ссылка: несколько устройств (``devs``), только просмотр и выбор вариантов.
        ``mode="space"`` — панель пространства ``w["space"]``: ``ttl=0`` — без срока, ``limit`` устройств (0 — сколько
        угодно), ``rights`` «full» или «read».
        ``mode="meeting"`` — протокол встречи ``mt``: окна нет, несколько устройств (до ``MEETING_MAX``)."""
        token, rid, now = secrets.token_urlsafe(32), secrets.token_hex(6), time.time()
        forever = mode == SPACE and not ttl
        ttl = FOREVER if forever else ttl
        with self._locked():
            d = {k: v for k, v in self._load().items() if self.live(v, now) or now - v.get("ended", now) < KEEP}
            d[rid] = {"h": _h(token), "w": w["id"], "path": w.get("path", ""), "name": w.get("name", ""),
                      **({"proj": proj} if proj else {}),
                      **({"mode": DEMO, "devs": {}, "opens": 0} if mode == DEMO else {}),
                      **({"mode": MEETING, "mt": str(mt), "devs": {}, "opens": 0} if mode == MEETING else {}),
                      **({"mode": SPACE, "devs": {}, "max": int(limit), "forever": forever,
                          "rights": "read" if rights == "read" else "full",
                          # для кого (штаб 21.11): «client» — человек сам соглашается с условиями строкой при первом
                          # действии; «self» — владелец или его тестировщик, условия отмечены выпуском ссылки
                          "aud": "self" if audience == "self" else "client"} if mode == SPACE else {}),
                      "space": w.get("space") or None, "by": by, "created": int(now), "exp": int(now + ttl),
                      "dev": None, "device": "", "opened": None, "state": "active"}
            self._save(d)
        return {"token": token, "id": rid, "exp": int(now + ttl)}

    def _by_token(self, d: dict, token: str, now: float | None = None) -> str | None:
        """Запись по токену: основному или дополнительному (``extra``, пока не истёк его срок)."""
        token = str(token or "")
        if not TOKEN_LEN[0] <= len(token) <= TOKEN_LEN[1]:
            return None
        h, now = _h(token), time.time() if now is None else now
        for k, v in d.items():
            if hmac.compare_digest(v.get("h", ""), h):
                return k
            if any(hmac.compare_digest(x, h) and now < e for x, e in (v.get("extra") or {}).items()):
                return k
        return None

    def check_token(self, token: str) -> dict | None:
        """Действующая ссылка по токену (для «Отправить себе», QR): запись или None."""
        d = self._load()
        k = self._by_token(d, token)
        return {**d[k], "id": k} if k and self.live(d[k]) else None

    @staticmethod
    def limit_of(rec: dict) -> int:
        """Сколько устройств у записи (0 — без ограничения)."""
        if rec.get("mode") == SPACE:
            return int(rec.get("max") or 0)
        return {DEMO: DEMO_MAX, MEETING: MEETING_MAX}.get(rec.get("mode") or "", FOCUS_MAX)

    @staticmethod
    def _devs(rec: dict) -> dict:
        devs = rec.setdefault("devs", {})
        if rec.get("dev") and rec["dev"] not in devs:         # старая запись: одно устройство в поле dev
            devs[rec["dev"]] = {"device": rec.get("device", ""), "opened": rec.get("opened")}
        return devs

    def seats(self, rid: str) -> dict:
        """Места устройств записи: {used, max, live} — для «Открыть на другом устройстве» и запроса доступа."""
        rec = self._load().get(str(rid or ""))
        if not rec:
            raise LookupError("ссылки нет")
        return {"used": len(self._devs(dict(rec))), "max": self.limit_of(rec), "live": self.live(rec)}

    def add_device(self, rid: str) -> dict:
        """«Открыть на другом устройстве»: одноразовый токен той же записи на ``EXTRA_TTL`` — {token, exp, used, max}.
        Мест нет — ``Denied`` (409 full): дополнительный токен не даёт устройств сверх лимита записи."""
        with self._locked():
            d, now = self._load(), time.time()
            rec = d.get(str(rid or ""))
            if not rec or not self.live(rec, now):
                raise Gone(self.why(rec) if rec else "Ссылки уже нет.", self.reason(rec) if rec else "bad")
            if rec.get("mode") == MEETING:
                raise Denied("ссылку на протокол пересылают целиком — она открывается на нескольких устройствах")
            lim, used = self.limit_of(rec), len(self._devs(rec))
            if lim and used >= lim:
                raise Denied(f"Все места заняты: ссылка открыта на {used} из {lim} устройств. Попросите владельца "
                             "отозвать ссылку и выпустить новую.", "full", 409)
            token = secrets.token_urlsafe(32)
            extra = {h: e for h, e in (rec.get("extra") or {}).items() if now < e}
            extra[_h(token)] = int(now + EXTRA_TTL)
            rec["extra"] = dict(list(extra.items())[-10:])        # не больше 10 неиспользованных — память не растёт
            self._save(d)
            return {"token": token, "exp": int(now + EXTRA_TTL), "used": used, "max": lim}

    def _spend_extra(self, rec: dict, token: str):
        """Дополнительный токен одноразовый: после открытия устройства — стираем его хэш."""
        h = _h(str(token or ""))
        if h in (rec.get("extra") or {}):
            rec["extra"].pop(h)

    # ---------- «Попросить доступ» (страница без действующей ссылки) ----------
    def _asks_path(self) -> Path:
        return self.store.with_name("focus_asks.json")

    def ask(self, rid: str, why: str, note: str, device: str) -> dict:
        """Запрос доступа: {id, rid, name, why, note, device, at}. ``rid`` — запись, если её удалось узнать."""
        rec = self._load().get(rid) if rid else None
        aid, now = secrets.token_hex(6), int(time.time())
        a = {"rid": rid if rec else "", "name": (rec or {}).get("name", ""), "why": str(why or "")[:20],
             "note": " ".join(str(note or "").split())[:120], "device": str(device or "")[:60], "at": now}
        p = self._asks_path()
        with jstore.locked(p):
            d = {k: v for k, v in jstore.load(p).items() if now - v.get("at", 0) < ASKS_KEEP}
            d[aid] = a
            jstore.save(p, dict(list(d.items())[-ASKS_MAX:]), ensure_ascii=False)
        return {"id": aid, **a}

    def ask_get(self, aid: str) -> dict:
        """Запрос доступа и его ссылка (для владельца): {id, ..., link: {id, name, w, proj, mode, used, max, live}}."""
        a = jstore.load(self._asks_path()).get(str(aid or ""))
        if not a:
            raise LookupError("запроса нет или прошли сутки")
        rec = self._load().get(a["rid"]) if a.get("rid") else None
        link = None
        if rec:
            link = {"id": a["rid"], "name": rec.get("name", ""), "w": rec.get("w") or "", "proj": rec.get("proj"),
                    "mode": rec.get("mode") or "", "used": len(self._devs(dict(rec))), "max": self.limit_of(rec),
                    "live": self.live(rec), "why": "" if self.live(rec) else self.why(rec)}
        return {"id": str(aid), **a, "link": link}

    def rid_by_token(self, token: str) -> str:
        """Запись по токену — любая, даже погасшая (для «Попросить доступ» сверх лимита и после срока); нет — ""."""
        return self._by_token(self._load(), token) or ""

    def open(self, token: str, cookie: str, device: str = "") -> tuple[str, dict]:
        """Открыть ссылку: первое открытие привязывает устройство — (значение cookie, запись). Уже привязана — только
        к тому же устройству (cookie совпадает). Иначе ``Gone`` с объяснением."""
        with self._locked():
            d = self._load()
            k = self._by_token(d, token)
            if not k:
                raise Gone("Ссылка неверна или устарела — попросите новую.", "bad")
            rec = d[k]
            if not self.live(rec):
                raise Gone(self.why(rec), self.reason(rec), k)
            if self.is_demo(rec) or self.is_meeting(rec):
                return self._open_demo(d, k, rec, cookie, device, token)
            if self._match(k, rec, cookie):
                return cookie, {**rec, "id": k}
            devs = self._devs(rec)
            lim = self.limit_of(rec)
            if lim and len(devs) >= lim:
                raise Gone(f"Ссылку уже открыли на {lim} {'устройстве' if lim == 1 else 'устройствах'}. Попросите "
                           "новую ссылку или отзовите эту: «Настройки» → «Команда и клиенты» → «Фокус-ссылки».",
                           "limit", k)
            secret, now = secrets.token_urlsafe(32), int(time.time())
            devs[_h(secret)] = {"device": device[:60], "opened": now}
            self._spend_extra(rec, token)
            rec.setdefault("dev", _h(secret))                    # первое устройство — как раньше (совместимость)
            rec.update(device=device[:60], opened=now)
            self._save(d)
            return f"{k}.{secret}", {**rec, "id": k}

    def _open_demo(self, d: dict, k: str, rec: dict, cookie: str, device: str, token: str = "") -> tuple[str, dict]:
        """Демо-ссылка (и ссылка на протокол): то же устройство — его cookie; новое — своё cookie, пока устройств меньше
        ``DEMO_MAX`` (у протокола — ``MEETING_MAX``)."""
        if self._match(k, rec, cookie):
            return cookie, {**rec, "id": k}
        devs = rec.setdefault("devs", {})
        lim = MEETING_MAX if self.is_meeting(rec) else DEMO_MAX
        if len(devs) >= lim:
            raise Gone(f"Ссылку уже открыли на {lim} устройствах — попросите новую.", "limit", k)
        secret, now = secrets.token_urlsafe(32), int(time.time())
        devs[_h(secret)] = {"device": device[:60], "opened": now}
        self._spend_extra(rec, token)
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
        return rec.get("mode") not in (DEMO, MEETING) and bool(rec.get("dev")) and hmac.compare_digest(rec["dev"], h)

    def by_cookie(self, cookie: str) -> dict:
        """Запись по cookie устройства: действующая — {..., id}; погасла — ``Gone``; cookie чужой или нет — ``Gone``."""
        rid = str(cookie or "").partition(".")[0]
        rec = self._load().get(rid) if rid else None
        if not rec or not self._match(rid, rec, cookie):
            raise Gone("Фокус-ссылка не открыта на этом устройстве. Откройте ссылку ещё раз.", "nodevice")
        if not self.live(rec):
            raise Gone(self.why(rec), self.reason(rec), rid)
        return {**rec, "id": rid}

    def space_by_cookie(self, cookie: str) -> dict | None:
        """Ссылка на пространство этого устройства: действует — запись; cookie не от неё — None; погасла — ``Gone``."""
        rid = str(cookie or "").partition(".")[0]
        rec = self._load().get(rid) if rid else None
        if not rec or rec.get("mode") != SPACE or not self._match(rid, rec, cookie):
            return None
        if not self.live(rec):
            raise Gone(self.why(rec), self.reason(rec), rid)
        return {**rec, "id": rid}

    def person(self, uid) -> dict | None:
        """«Человек» ссылки на пространство (``People.virtual``): {role, tenant} пока ссылка жива, иначе None."""
        rid = rid_of(uid)
        rec = self._load().get(rid) if rid else None
        if not rec or rec.get("mode") != SPACE or not self.live(rec) or not rec.get("space"):
            return None
        return {"role": "viewer" if rec.get("rights") == "read" else "member", "tenant": rec["space"]}

    @staticmethod
    def reason(rec: dict) -> str:
        """Причина погасшей записи — для экрана страницы: closed, revoked или expired."""
        return rec.get("state") if rec.get("state") in ("closed", "revoked") else "expired"

    @staticmethod
    def why(rec: dict) -> str:
        if rec.get("state") == "closed":
            return "Проект удалён." if rec.get("proj") else "Чат завершён."
        if rec.get("state") == "revoked":
            if rec.get("mode") == MEETING:
                return "Владелец отозвал ссылку на этот протокол."
            return f"Владелец отозвал эту {'демо' if rec.get('mode') == DEMO else 'фокус'}-ссылку."
        if rec.get("mode") == MEETING:
            return "Срок ссылки на протокол вышел — попросите новую."
        if rec.get("mode") == SPACE:
            return "Срок ссылки вышел — попросите новую."
        return "Срок фокус-ссылки вышел — попросите новую."

    def end(self, rid: str, state: str = "closed") -> bool:
        with self._locked():
            d = self._load()
            rec = d.get(rid)
            if not rec or not self.live(rec):
                return False
            rec.update(state=state, ended=int(time.time()))
            self._save(d)
            return True

    def end_window(self, wid: str) -> int:
        """Сессию завершили — гасим все её ссылки сразу."""
        with self._locked():
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
        with self._locked():
            d, n = self._load(), 0
            for rec in d.values():
                if old and rec.get("w") == old and not rec.get("proj") and self.live(rec):
                    rec["w"] = new
                    n += 1
            if n:
                self._save(d)
            return n

    def add_chat(self, rid: str, sid: str) -> bool:
        """Чат начат (или продолжен) по ссылке ``rid``: его id — в записи ссылки. Только такие завершённые чаты ссылка
        показывает и продолжает (штаб 25.11: чаты проекта, начатые владельцем, по ссылке не видны)."""
        sid = str(sid or "")
        if not sid:
            return False
        with self._locked():
            d = self._load()
            rec = d.get(str(rid or ""))
            if not rec or sid in (rec.get("sids") or []):
                return False
            rec["sids"] = [*(rec.get("sids") or []), sid][-CHATS_MAX:]
            self._save(d)
            return True

    @staticmethod
    def chats(rec: dict) -> set[str]:
        """Чаты, начатые по этой ссылке (``add_chat``) или возвращённые ей владельцем (штаб 25.11)."""
        return {str(x) for x in rec.get("sids") or []}

    @staticmethod
    def whole_project(rec: dict) -> bool:
        """Ссылка видит весь проект — все окна и все завершённые чаты, как до 25.11: демо-ссылка (показ клиенту) и
        личная ссылка владельца (флаг ``owner_link``: владелец открывает свой проект на другом устройстве, людям её не
        дают; штаб 25.11 — ссылки владельца на штаб). Флаг ставит только владелец, вручную; по умолчанию его нет."""
        return Focus.is_demo(rec) or rec.get("owner_link") is True

    @staticmethod
    def owns_window(rec: dict, w: dict) -> bool:
        """Окно — этой ссылки: в метке ``@gas_pult_focus`` её id (меток может быть несколько, через пробел — у проекта
        бывает несколько ссылок) или разговор окна записан в ссылке (``chats``: вернули чат — видно и живое окно)."""
        rid = str(rec.get("id") or "")
        return bool(rid) and (rid in str(w.get("focus") or "").split() or str(w.get("sid") or "") in Focus.chats(rec))

    def set_browser(self, rid: str, on: bool) -> bool:
        """Разрешить (или запретить) фокус-пользователю подключить свой браузер (владелец 17.11)."""
        with self._locked():
            d = self._load()
            rec = d.get(str(rid or ""))
            if not rec or not self.live(rec) or self.is_demo(rec) or rec.get("mode") in (SPACE, MEETING):
                return False
            rec["browser"] = bool(on)
            self._save(d)
            return True

    @staticmethod
    def auto_adopt(rec: dict) -> bool:
        """Новые окна владельца в папке проекта видны по этой ссылке (владелец 25.11: по умолчанию — да; выключается
        у ссылки в «Настройки» → «Фокус-ссылки»)."""
        return rec.get("auto_adopt") is not False

    def set_auto_adopt(self, rid: str, on: bool) -> bool:
        """Переключатель «Новые окна владельца видны человеку» у ссылки на проект (не демо, не пространство)."""
        with self._locked():
            d = self._load()
            rec = d.get(str(rid or ""))
            if not rec or not self.live(rec) or not rec.get("proj") or self.is_demo(rec) or rec.get("space"):
                return False
            rec["auto_adopt"] = bool(on)
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
                "created": v.get("created"), "browser": bool(v.get("browser")), "auto_adopt": Focus.auto_adopt(v),
                "exp": v.get("exp"), "opened": v.get("opened"), "device": v.get("device", ""),
                **({"mode": DEMO, "devices": len(v.get("devs") or {}), "opens": v.get("opens", 0)}
                   if v.get("mode") == DEMO else {}),
                **({"mode": MEETING, "mt": v.get("mt"), "devices": len(v.get("devs") or {}), "opens": v.get("opens", 0)}
                   if v.get("mode") == MEETING else {}),
                **({"mode": SPACE, "devices": len(v.get("devs") or {}), "max": v.get("max", 0),
                    "rights": v.get("rights", "full"), "forever": bool(v.get("forever"))}
                   if v.get("mode") == SPACE else {})}
               for k, v in self._load().items() if self.live(v, now)]
        return sorted(out, key=lambda x: -(x["created"] or 0))
