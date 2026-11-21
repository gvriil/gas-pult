"""Куда и о чём сообщать (уведомления, часть B): каналы «На телефон / Telegram / Почта» и выбор событий.

Одна точка доставки: бот спрашивает ``route()`` — и шлёт только в выбранные каналы. Каналы и события у каждого свои,
файл ``<data>/notify_channels.json`` (0600): ``{uid: {"push": bool, "telegram": bool, "events": {вид: bool}}}``.
Почта — флаг ``notify`` в записи почты человека (emailcode.py): один выключатель на оба экрана.

Правила, чтобы ничего не потерялось:
- Сообщение с кнопками решения (запрос доступа, «продолжить при расходе», срочное) уходит в Telegram всегда:
  кнопки работают только там.
- Ни одного рабочего канала (Telegram выключен, устройств нет, почты нет) — шлём в Telegram.
- Ответы чатов в почту не идут: письмо на каждый ответ — это спам.
- По умолчанию всё включено, почта — выключена: прежнее поведение не меняется, пока человек сам не выберет.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

CHANNELS = ("push", "telegram", "email")
# вид события → подпись в «Уведомлениях»
EVENTS = {
    "answer": "Ответы чатов",
    "dialog": "Чат ждёт вашего выбора",
    "error": "Сбои и лимиты",
    "brief": "Брифинг и расписание",
    "people": "Люди и вход",
}
DEFAULT = {"push": True, "telegram": True}
NO_EMAIL = {"answer"}


def norm(rec: dict | None) -> dict:
    """Полная запись с умолчаниями; лишние ключи и не-bool отбрасываются."""
    rec = rec if isinstance(rec, dict) else {}
    ev = rec.get("events") if isinstance(rec.get("events"), dict) else {}
    out = {k: rec[k] if isinstance(rec.get(k), bool) else v for k, v in DEFAULT.items()}
    out["events"] = {k: ev[k] if isinstance(ev.get(k), bool) else True for k in EVENTS}
    return out


def route(rec: dict | None, kind: str, *, push: bool, email: bool, action: bool = False) -> set[str]:
    """Каналы для события ``kind``. ``push`` — есть подписанные устройства, ``email`` — почта включена и адрес есть,
    ``action`` — в сообщении кнопки решения (работают только в Telegram)."""
    r = norm(rec)
    kind = kind if kind in EVENTS else "error"
    if not r["events"][kind] and not action:
        return set()
    out = set()
    if r["telegram"] or action:
        out.add("telegram")
    if r["push"] and push:
        out.add("push")
    if email and kind not in NO_EMAIL:
        out.add("email")
    return out or {"telegram"}


class Store:
    """Настройки каналов: читаются при каждой отправке (бот и панель — разные процессы, файл общий)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def _all(self) -> dict:
        try:
            d = json.loads(self.path.read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def get(self, uid) -> dict:
        return norm(self._all().get(str(uid)))

    def set(self, uid, patch: dict) -> dict:
        """Поменять только присланное: ``push``/``telegram`` — bool, ``events`` — {вид: bool}."""
        if not isinstance(patch, dict):
            raise ValueError("ожидается объект")
        with self.lock:
            d = self._all()
            rec = norm(d.get(str(uid)))
            for k in DEFAULT:
                if k in patch:
                    if not isinstance(patch[k], bool):
                        raise ValueError(f"{k}: да или нет")
                    rec[k] = patch[k]
            ev = patch.get("events")
            if ev is not None:
                if not isinstance(ev, dict) or any(k not in EVENTS or not isinstance(v, bool) for k, v in ev.items()):
                    raise ValueError("события: " + ", ".join(EVENTS))
                rec["events"].update(ev)
            d[str(uid)] = rec
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = self.path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(d, ensure_ascii=False))
            os.replace(tmp, self.path)
            return rec
