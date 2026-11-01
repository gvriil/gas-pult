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
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from gas_pult import country as geo
from gas_pult.config import data_dir, write_private
from gas_pult.terms import VERSION as TERMS_VERSION

ROLES = ("member", "viewer")
FIELDS = ("chosen", "phone_cc", "phone_hash", "phone_at", "ip_cc", "ip_at")
RANK = {"viewer": 1, "member": 2, "owner": 3}
TITLES = {"owner": "владелец", "member": "участник", "viewer": "наблюдатель"}


class People:
    def __init__(self, store: Path, owners: list[int]):
        self.store, self.owners, self.lock = store, list(owners), threading.Lock()
        self.terms_store = store.with_name("terms.json")      # согласие владельцев и тех, кого нет в people.json
        self.country_store = store.with_name("countries.json")   # их же страна (признаки — country.py)

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

    def add(self, uid: int, role: str, name: str = "", username: str = ""):
        if role not in ROLES:
            raise ValueError("роль: участник или наблюдатель")
        if int(uid) in self.owners:
            raise ValueError("это владелец — у него и так всё")
        with self.lock:
            d = self._load()
            old = d.get(str(int(uid))) or {}
            rec = {"role": role, "name": name[:60], "username": username[:40],
                   "added": old.get("added") or int(time.time())}
            for k in ("terms", "country"):                         # смена роли не сбрасывает согласие и страну
                if old.get(k):
                    rec[k] = old[k]
            d[str(int(uid))] = rec
            self._save(d)

    def remove(self, uid: int):
        """Отключить человека: роль и согласие удаляются, любой его вход перестаёт работать сразу."""
        with self.lock:
            d = self._load()
            if d.pop(str(int(uid)), None) is not None:
                self._save(d)
            for f in (self.terms_store, self.country_store):
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

    def list(self) -> list[dict]:
        t, c = self._load_terms(), self._load_side(self.country_store)
        out = [{"id": o, "role": "owner", "name": "", "username": "", **({"terms": t[str(o)]} if str(o) in t else {}),
                **({"country": c[str(o)]} if str(o) in c else {})} for o in self.owners]
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
    return d


def home_of(w: dict, data: Path | None = None) -> Path | None:
    """Папка Claude Code окна — по отметке ``@gas_pult_by`` (кто открыл); без отметки — владельца (None)."""
    by = str(w.get("by") or "")
    return (data or data_dir()) / "people" / by / "claude" if by.isdigit() else None
