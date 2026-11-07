"""Люди пульта и их роли.

- **Владелец** (``owners`` в config.toml) — всё: сессии, «Выполнить», ключи, интеграции, люди.
- **Участник** — работа с сессиями: писать, отвечать на вопросы, команды, модель, новые сессии, файлы.
- **Наблюдатель** — только смотреть.

Участники и наблюдатели — в ``<data>/people.json`` (0600): Telegram ID → имя, @username, роль. Добавляет владелец
(кнопкой в боте на запрос человека или в «Настройках» панели). Роль проверяется на каждый запрос — убрали человека,
и его вход перестаёт работать сразу.

У каждого человека из people.json — своя папка Claude Code ``<data>/people/<id>/claude`` (``CLAUDE_CONFIG_DIR``):
свой вход в Claude, свои MCP и коннекторы claude.ai, свои журналы. Владелец — ``~/.claude``, как раньше
(docs/adr/0001-claude-config-per-person.md).

Согласие с условиями использования (``terms.py``): у человека из people.json — поле ``terms: {version, at}`` в его
записи (``at`` — unix-время). Владельцев в people.json нет, поэтому их согласие (и любого, у кого нет записи) —
в ``<data>/terms.json`` (0600): ``{"<Telegram ID>": {version, at}}``. Так формат people.json прежний: ``list()``,
``role()`` и старые версии пульта его читают как раньше. Убрали человека — его согласие удаляется вместе с ним.

Страна (``country.py``): у человека из people.json — поле ``country: {chosen, phone_cc, phone_hash, phone_at, ip_cc,
ip_at, mismatch}``; у владельцев (и у тех, кого нет в people.json) — рядом, в ``<data>/countries.json`` (0600), тем же
видом. Номер телефона и IP не хранятся — только хеш номера с солью и коды стран.

Короткий тур по панели (``index.html``, docs/MINI_APP.md#тур): у человека из people.json — поле ``tour: {business,
dev, at}`` (``"done"`` — проходил, ``"dismissed"`` — «Не сейчас», ``null`` — ещё нет); у владельцев — в
``<data>/tours.json`` (0600) тем же видом. Это его настройка: менять может и наблюдатель.

Почта (``emailcode.py``): у человека из people.json — поле ``email: {address, at, second_factor, notify}``; у владельцев
— рядом, в ``<data>/emails.json`` (0600), тем же видом. Адрес подтверждён кодом; по нему можно войти, пока у человека
есть роль.

Вид панели (``personas.py``): у человека из people.json — поле ``ui: {persona, added, hidden, onboarded}``; у владельцев
— ``<data>/ui.json`` (0600) тем же видом. Это его настройка: менять может и наблюдатель (в пределах потолка).

Настройки человека (``prefs``): простой режим панели и язык интерфейса — ``{simple: bool, lang: "ru"|"en"}``; у
человека из people.json — поле ``prefs`` в его записи, у владельцев — ``<data>/prefs.json`` (0600). Нет записи —
полный режим и русский, как раньше.

Гость без Telegram (задача 34, ``invites.py``): человек вошёл по приглашению — ссылкой или коротким кодом — и назвал
только имя. Ключ его записи — внутренний **отрицательный** ID не больше ``GUEST_FLOOR`` (у людей Telegram ID
положительный, у групп и каналов — от −10¹³ и выше, ``webauth.LEGACY`` = −1), в записи ``kind: "guest"``, ``name`` и
``tenant`` — гость всегда тестировщик своего пространства. Всё, что пишет человеку в Telegram (кнопка «📱 Панель»,
«сообщить по готовности», рассылки), гостей пропускает (``has_telegram``). «Привязать Telegram» (``adopt``) переносит
запись целиком — роль, пространство, согласия, страну, настройки — под его Telegram ID, и гость исчезает.
У любого человека из people.json панель запоминает последний вход: ``last: {at, device}`` — без IP.
"""

from __future__ import annotations

import json
import secrets
import sys
import threading
import time
from pathlib import Path

from gas_pult import country as geo
from gas_pult import secrets_guard, tenants
from gas_pult.config import data_dir, write_private
from gas_pult.terms import VERSION as TERMS_VERSION

ROLES = ("member", "viewer")
FIELDS = ("chosen", "phone_cc", "phone_hash", "phone_at", "ip_cc", "ip_at")
RANK = {"viewer": 1, "member": 2, "owner": 3}
TITLES = {"owner": "владелец", "member": "участник", "viewer": "наблюдатель"}
LANGS = ("ru", "en")
PREFS = {"simple": False, "lang": "ru"}            # по умолчанию — полный режим и русский: у текущих ничего не меняется
TOURS = ("business", "dev")                 # тур для бизнеса и для разработчика
TOUR_STATES = ("done", "dismissed")
GUEST_FLOOR = -(10 ** 15)                   # гости — от −2·10¹⁵ до −10¹⁵: ни с Telegram ID, ни с группами не совпадут


def is_guest(uid) -> bool:
    """Внутренний ID гостя без Telegram (а не Telegram ID)."""
    try:
        return int(uid) <= GUEST_FLOOR
    except (TypeError, ValueError):
        return False


def has_telegram(uid) -> bool:
    """Можно ли писать человеку в Telegram: настоящий ID пользователя (положительный)."""
    try:
        return int(uid) > 0
    except (TypeError, ValueError):
        return False


class People:
    def __init__(self, store: Path, owners: list[int]):
        self.store, self.owners, self.lock = store, list(owners), threading.Lock()
        self.terms_store = store.with_name("terms.json")      # согласие владельцев и тех, кого нет в people.json
        self.country_store = store.with_name("countries.json")   # их же страна (признаки — country.py)
        self.prefs_store = store.with_name("prefs.json")          # их же настройки панели (простой режим, язык)
        self.email_store = store.with_name("emails.json")         # их же почта (emailcode.py)
        self.tour_store = store.with_name("tours.json")          # их же отметки тура
        self.ui_store = store.with_name("ui.json")               # их же вид панели (роль интерфейса)

    def _load(self) -> dict:
        try:
            return json.loads(self.store.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, d: dict):
        write_private(self.store, json.dumps(d, ensure_ascii=False))

    def _load_terms(self) -> dict:
        return self._load_side(self.terms_store)

    @staticmethod
    def _load_side(f: Path) -> dict:
        try:
            d = json.loads(f.read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def role(self, uid) -> str | None:
        """«owner», «member», «viewer» или None (нет доступа)."""
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            return None
        if uid in self.owners:
            return "owner"
        p = self._load().get(str(uid))
        return p["role"] if p and p.get("role") in ROLES else None

    def add(self, uid: int, role: str, name: str = "", username: str = "", tenant: str | None = None):
        """``tenant`` — тестировщик демо-пространства (задача 31): его сессии — только там. None — оставить как было
        (смена роли его не снимает), "" — снять."""
        if role not in ROLES:
            raise ValueError("роль: участник или наблюдатель")
        if int(uid) in self.owners:
            raise ValueError("это владелец — у него и так всё")
        with self.lock:
            d = self._load()
            old = d.get(str(int(uid))) or {}
            rec = {"role": role, "name": name[:60], "username": username[:40],
                   "added": old.get("added") or int(time.time())}
            for k in ("terms", "country", "email", "tour", "prefs", "ui", "kind", "last"):   # смена роли — не сброс
                if old.get(k):
                    rec[k] = old[k]
            space = old.get("tenant", "") if tenant is None else tenant
            if space:                                    # имя — по тем же правилам, что у pult-tenant
                rec["tenant"] = tenants.check_slug(space)
            d[str(int(uid))] = rec
            self._save(d)

    def add_guest(self, name: str, role: str, tenant: str) -> int:
        """Новый гость без Telegram — тестировщик пространства ``tenant``. Возвращает его внутренний ID."""
        name = " ".join(str(name or "").split())[:60]
        if not name:
            raise ValueError("напишите, как вас зовут")
        if role not in ROLES:
            raise ValueError("роль: участник или наблюдатель")
        tenant = tenants.check_slug(tenant)
        with self.lock:
            d = self._load()
            while str(uid := GUEST_FLOOR - secrets.randbelow(10 ** 15)) in d:
                pass
            d[str(uid)] = {"role": role, "name": name, "username": "", "added": int(time.time()), "tenant": tenant,
                           "kind": "guest"}
            self._save(d)
        return uid

    def seen(self, uid, device: str = ""):
        """Вход в панель: когда и с какого устройства (коротко, без IP) — владелец видит это в «Людях»."""
        try:
            key = str(int(uid))
        except (TypeError, ValueError):
            return
        with self.lock:
            d = self._load()
            if key in d:
                d[key]["last"] = {"at": int(time.time()), "device": str(device or "")[:60]}
                self._save(d)

    def adopt(self, guest: int, tg_uid: int, name: str = "", username: str = "") -> dict:
        """«Привязать Telegram»: запись гостя целиком (роль, пространство, согласия, страна, настройки) — под его
        Telegram ID; гость исчезает. Этот Telegram уже в пульте — отказ (две записи не сливаем)."""
        guest, tg_uid = int(guest), int(tg_uid)
        if not is_guest(guest) or not has_telegram(tg_uid):
            raise ValueError("привязать можно только вход без Telegram")
        if tg_uid in self.owners:
            raise ValueError("это Telegram владельца пульта")
        with self.lock:
            d = self._load()
            if str(tg_uid) in d:
                raise ValueError("этот Telegram уже есть в пульте — войдите через него")
            rec = d.pop(str(guest), None)
            if not rec or rec.get("role") not in ROLES:
                raise ValueError("вход уже отключён")
            rec.pop("kind", None)
            rec["name"] = rec.get("name") or name[:60]
            rec["username"] = username[:40]
            d[str(tg_uid)] = rec
            self._save(d)
        return rec

    def tenant(self, uid) -> str | None:
        """Пространство тестировщика (``tenant`` в people.json) или None. Владельцу — никогда."""
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            return None
        if uid in self.owners:
            return None
        p = self._load().get(str(uid)) or {}
        return p.get("tenant") or None if p.get("role") in ROLES else None

    def remove(self, uid: int):
        """Отключить человека: роль и согласие удаляются, любой его вход перестаёт работать сразу."""
        with self.lock:
            d = self._load()
            if d.pop(str(int(uid)), None) is not None:
                self._save(d)
            for f in (self.terms_store, self.country_store, self.email_store, self.tour_store, self.prefs_store,
                      self.ui_store):
                t = self._load_side(f)
                if t.pop(str(int(uid)), None) is not None:
                    write_private(f, json.dumps(t))

    def accept(self, uid: int, version: str = TERMS_VERSION):
        """Человек принял условия версии ``version`` — запомнить с датой."""
        uid, rec = int(uid), {"version": version, "at": int(time.time())}
        with self.lock:
            d = self._load()
            if uid not in self.owners and str(uid) in d:
                d[str(uid)]["terms"] = rec
                return self._save(d)
            t = self._load_terms()
            t[str(uid)] = rec
            write_private(self.terms_store, json.dumps(t))

    def terms(self, uid) -> dict | None:
        """Последнее согласие человека: {version, at} или None."""
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            return None
        p = None if uid in self.owners else self._load().get(str(uid))
        rec = (p or {}).get("terms") or self._load_terms().get(str(uid))
        return rec if isinstance(rec, dict) else None

    def accepted(self, uid, version: str = TERMS_VERSION) -> bool:
        """Принял ли человек условия именно этой версии (версия сменилась — спрашиваем заново)."""
        return (self.terms(uid) or {}).get("version") == version

    def country(self, uid) -> dict:
        """Страна человека — запись признаков (``country.py``); нет — пустая."""
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            return {}
        p = None if uid in self.owners else self._load().get(str(uid))
        rec = (p or {}).get("country") if p else self._load_side(self.country_store).get(str(uid))
        return dict(rec) if isinstance(rec, dict) else {}

    def set_country(self, uid: int, **fields) -> tuple[dict, bool]:
        """Обновить признаки страны. Возвращает (запись, сказать ли владельцам): признаки разошлись впервые или
        набор стран при расхождении поменялся."""
        uid = int(uid)
        with self.lock:
            d = self._load()
            mine = uid not in self.owners and str(uid) in d
            side = {} if mine else self._load_side(self.country_store)
            old = dict((d[str(uid)].get("country") if mine else side.get(str(uid))) or {})
            rec = {**old, **{k: v for k, v in fields.items() if k in FIELDS}}
            rec["mismatch"] = geo.is_mismatch(rec)
            tell = rec["mismatch"] and (not old.get("mismatch") or geo.effective(old) != geo.effective(rec))
            if mine:
                d[str(uid)]["country"] = rec
                self._save(d)
            else:
                side[str(uid)] = rec
                write_private(self.country_store, json.dumps(side))
        return rec, tell

    def prefs(self, uid) -> dict:
        """Настройки панели человека: {simple, lang, saved}; ``saved`` — есть ли запись (иначе панель может
        дописать выбор языка с первого экрана)."""
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            return {**PREFS, "saved": False}
        p = None if uid in self.owners else self._load().get(str(uid))
        rec = (p or {}).get("prefs") if p else self._load_side(self.prefs_store).get(str(uid))
        rec = rec if isinstance(rec, dict) else {}
        return {"simple": rec.get("simple") is True, "lang": rec.get("lang") if rec.get("lang") in LANGS else "ru",
                "saved": bool(rec)}

    def set_prefs(self, uid: int, simple=None, lang=None) -> dict:
        """Поменять настройки: ``None`` — оставить как было. Язык — только ru или en."""
        if lang is not None and lang not in LANGS:
            raise ValueError("язык — ru или en")
        uid = int(uid)
        with self.lock:
            d = self._load()
            mine = uid not in self.owners and str(uid) in d
            side = {} if mine else self._load_side(self.prefs_store)
            old = dict((d[str(uid)].get("prefs") if mine else side.get(str(uid))) or {})
            rec = {**PREFS, **{k: v for k, v in old.items() if k in PREFS}}
            if simple is not None:
                rec["simple"] = bool(simple)
            if lang is not None:
                rec["lang"] = lang
            if mine:
                d[str(uid)]["prefs"] = rec
                self._save(d)
            else:
                side[str(uid)] = rec
                write_private(self.prefs_store, json.dumps(side))
        return {**rec, "saved": True}

    def tour(self, uid) -> dict:
        """Отметки тура человека: ``{business, dev, at}``; чего нет — None."""
        empty = {"business": None, "dev": None, "at": None}
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            return empty
        p = None if uid in self.owners else self._load().get(str(uid))
        rec = (p or {}).get("tour") if p else self._load_side(self.tour_store).get(str(uid))
        rec = rec if isinstance(rec, dict) else {}
        out = {k: rec.get(k) if rec.get(k) in TOUR_STATES else None for k in TOURS}
        return {**out, "at": rec.get("at") if isinstance(rec.get("at"), int) else None}

    def set_tour(self, uid: int, kind: str, state: str) -> dict:
        """Запомнить отметку тура ``kind`` (business | dev): done или dismissed."""
        if kind not in TOURS or state not in TOUR_STATES:
            raise ValueError("тур: business или dev; отметка: done или dismissed")
        uid = int(uid)
        with self.lock:
            rec = {**self.tour(uid), kind: state, "at": int(time.time())}
            d = self._load()
            if uid not in self.owners and str(uid) in d:
                d[str(uid)]["tour"] = rec
                self._save(d)
            else:
                side = self._load_side(self.tour_store)
                side[str(uid)] = rec
                write_private(self.tour_store, json.dumps(side))
        return rec
    def ui(self, uid) -> dict:
        """Вид панели человека (``personas.py``): {persona, added, hidden, onboarded}; нет — пустая запись."""
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            return {}
        p = None if uid in self.owners else self._load().get(str(uid))
        rec = (p or {}).get("ui") if p else self._load_side(self.ui_store).get(str(uid))
        return dict(rec) if isinstance(rec, dict) else {}

    def set_ui(self, uid: int, rec: dict):
        """Сохранить вид панели целиком (запись готовит ``personas.change``)."""
        uid = int(uid)
        rec = {**{k: rec[k] for k in ("persona", "added", "hidden", "onboarded") if k in rec}, "at": int(time.time())}
        with self.lock:
            d = self._load()
            if uid not in self.owners and str(uid) in d:
                d[str(uid)]["ui"] = rec
                self._save(d)
            else:
                side = self._load_side(self.ui_store)
                side[str(uid)] = rec
                write_private(self.ui_store, json.dumps(side))

    def email(self, uid) -> dict:
        """Почта человека: {address, at, second_factor, notify} или пустая запись."""
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            return {}
        p = None if uid in self.owners else self._load().get(str(uid))
        rec = (p or {}).get("email") if p else self._load_side(self.email_store).get(str(uid))
        return dict(rec) if isinstance(rec, dict) else {}

    def set_email(self, uid: int, **fields):
        """Обновить почту человека; ``address=None`` — отвязать (вместе с настройками). Только тем, у кого есть роль."""
        uid = int(uid)
        if not self.role(uid):
            raise ValueError("у этого человека нет доступа к пульту")
        with self.lock:
            d = self._load()
            mine = uid not in self.owners and str(uid) in d
            side = {} if mine else self._load_side(self.email_store)
            old = dict((d[str(uid)].get("email") if mine else side.get(str(uid))) or {})
            if "address" in fields and fields["address"] is None:
                rec = None
            else:
                if fields.get("address") and fields["address"] != old.get("address"):
                    old = {}                                        # новый адрес — настройки с нуля
                rec = {**old, **{k: v for k, v in fields.items() if k in ("address", "at", "second_factor", "notify")}}
            if mine:
                if rec is None:
                    d[str(uid)].pop("email", None)
                else:
                    d[str(uid)]["email"] = rec
                self._save(d)
            else:
                if rec is None:
                    side.pop(str(uid), None)
                else:
                    side[str(uid)] = rec
                write_private(self.email_store, json.dumps(side))

    def by_email(self, addr: str) -> int | None:
        """Кому из людей с ролью принадлежит адрес (в нижнем регистре) — или None."""
        if not addr:
            return None
        side = self._load_side(self.email_store)
        for o in self.owners:
            if (side.get(str(o)) or {}).get("address") == addr:
                return o
        for k, v in self._load().items():
            if v.get("role") in ROLES and (v.get("email") or {}).get("address") == addr:
                return int(k)
        return None

    def list(self) -> list[dict]:
        t, c, m = self._load_terms(), self._load_side(self.country_store), self._load_side(self.email_store)
        out = [{"id": o, "role": "owner", "name": "", "username": "", **({"terms": t[str(o)]} if str(o) in t else {}),
                **({"country": c[str(o)]} if str(o) in c else {}),
                **({"email": m[str(o)]} if str(o) in m else {})} for o in self.owners]
        out += [{"id": int(k), **v} for k, v in self._load().items()]
        return out


def allowed(role: str | None, need: str) -> bool:
    return bool(role) and RANK[role] >= RANK[need]


def claude_dir(data: Path, uid, owners) -> Path | None:
    """Папка Claude Code человека (создаётся с правами 0700). Владелец или непонятный ID — None: ``~/.claude``."""
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return None
    if uid in owners or uid <= 0:
        return None
    d = data / "people" / str(uid) / "claude"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    for x in (d, d.parent, d.parent.parent):
        x.chmod(0o700)
    try:                                                # скрытие секретов — в каждой папке человека (secrets_guard)
        secrets_guard.install(d, out=None)
    except (OSError, ValueError) as e:
        print(f"secrets_guard: {d}: {type(e).__name__}", file=sys.stderr, flush=True)
    return d


def home_of(w: dict, data: Path | None = None) -> Path | None:
    """Папка Claude Code окна — по отметке ``@gas_pult_by`` (кто открыл); без отметки — владельца (None).

    Окна владельца тоже помечаются его ID (для запасных — по его странам), но своей папки у него нет: отметка без
    папки — учётка владельца (None). Участнику папку создаёт ``claude_dir`` до запуска окна."""
    if w.get("space"):                                  # окно демо-пространства — его папка Claude (tenants.py)
        return tenants.paths(w["space"])["claude"]
    by = str(w.get("by") or "")
    d = (data or data_dir()) / "people" / by / "claude"
    return d if by.isdigit() and d.is_dir() else None
