"""Люди пульта и их роли.

- **Владелец** (``owners`` в config.toml) — всё: сессии, «Выполнить», ключи, интеграции, люди.
- **Участник** — работа с сессиями: писать, отвечать на вопросы, команды, модель, новые сессии, файлы.
- **Наблюдатель** — только смотреть.

Участники и наблюдатели — в ``<data>/people.json`` (0600): Telegram ID → имя, @username, роль. Добавляет владелец
(кнопкой в боте на запрос человека или в «Настройках» панели). Роль проверяется на каждый запрос — убрали человека,
и его вход перестаёт работать сразу.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from gas_pult.config import write_private

ROLES = ("member", "viewer")
RANK = {"viewer": 1, "member": 2, "owner": 3}
TITLES = {"owner": "владелец", "member": "участник", "viewer": "наблюдатель"}


class People:
    def __init__(self, store: Path, owners: list[int]):
        self.store, self.owners, self.lock = store, list(owners), threading.Lock()

    def _load(self) -> dict:
        try:
            return json.loads(self.store.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, d: dict):
        write_private(self.store, json.dumps(d, ensure_ascii=False))

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
            d[str(int(uid))] = {"role": role, "name": name[:60], "username": username[:40], "added": int(time.time())}
            self._save(d)

    def remove(self, uid: int):
        with self.lock:
            d = self._load()
            if d.pop(str(int(uid)), None) is not None:
                self._save(d)

    def list(self) -> list[dict]:
        out = [{"id": o, "role": "owner", "name": "", "username": ""} for o in self.owners]
        out += [{"id": int(k), **v} for k, v in self._load().items()]
        return out


def allowed(role: str | None, need: str) -> bool:
    return bool(role) and RANK[role] >= RANK[need]
