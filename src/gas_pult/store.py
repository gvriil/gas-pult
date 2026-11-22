"""Хранилища JSON пульта: замок, атомарная запись, версия схемы.

Бот и панель — разные процессы и пишут одни файлы (``people.json``, ``focus.json``…). ``threading.Lock`` защищает
только потоки одного процесса: два процесса читали старое, каждый дописывал своё, и второй затирал первого (замер
22.11: 2 процесса × 200 записей в people.json → 229 из 400). Поэтому:

- ``with locked(path):`` — замок потоков (общий на файл в процессе, повторный вход в том же потоке — без ожидания)
  и ``fcntl.flock`` на ``.<файл>.lock`` рядом — тот же замок, что у ``tasks.py`` и ``webauth.py``;
- ``update(path, fn)`` — прочитать → изменить → записать под одним замком;
- запись — ``config.write_private``: 0600, временный файл и ``os.replace`` — обрыв записи файл не портит.

Версия схемы — поле ``_v`` в файле-словаре. ``MIGRATIONS[имя файла] = [(версия, fn), …]``: ``load`` применяет к
старому файлу (без ``_v`` — версия 0) все шаги новее его версии, ``save`` пишет текущую версию — файл переводится при
первой записи. Наружу ``_v`` не выходит: ``load`` его убирает, вид данных для кода и API — прежний.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path

from gas_pult.config import write_private

VERSION_KEY = "_v"


def _same(d):
    return d


# имя файла → шаги (версия, функция «старый вид → новый»), по возрастанию версий. 1 — вид до появления ``_v``.
MIGRATIONS: dict[str, list[tuple[int, Callable]]] = {
    name: [(1, _same)] for name in ("people.json", "terms.json", "countries.json", "prefs.json", "emails.json",
                                    "tours.json", "ui.json", "focus.json", "invites.json", "offer_tg.json",
                                    "passkeys.json", "brief_prefs.json")
}

_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}
_held = threading.local()


def _key(path: Path) -> str:
    return os.path.abspath(path)


@contextlib.contextmanager
def locked(path):
    """Замок файла ``path`` для потоков и процессов. Вложенный ``locked`` того же файла в том же потоке — без
    повторного ``flock`` (иначе процесс ждал бы сам себя)."""
    path = Path(path)
    key = _key(path)
    with _guard:
        lk = _locks.setdefault(key, threading.RLock())
    with lk:
        depth = getattr(_held, "d", None)
        if depth is None:
            depth = _held.d = {}
        if depth.get(key):
            depth[key] += 1
            try:
                yield
            finally:
                depth[key] -= 1
            return
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(path.with_name(f".{path.name}.lock"), "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            depth[key] = 1
            try:
                yield
            finally:
                depth[key] = 0
                fcntl.flock(fh, fcntl.LOCK_UN)


def version(name: str) -> int:
    """Текущая версия схемы файла ``name`` (0 — версий нет, ``_v`` не пишется)."""
    steps = MIGRATIONS.get(name)
    return steps[-1][0] if steps else 0


def migrate(name: str, d):
    """Привести прочитанное к текущей схеме: шаги новее ``_v`` файла. ``_v`` из результата убран."""
    if not isinstance(d, dict):
        return d
    d = dict(d)
    try:
        v = int(d.pop(VERSION_KEY, 0) or 0)
    except (TypeError, ValueError):
        v = 0
    for ver, fn in MIGRATIONS.get(name, ()):
        if ver > v:
            d = fn(d)
    return d


def load(path, default: Callable = dict, name: str | None = None):
    """Прочитать файл: нет, битый или не того вида (не ``type(default())``) — ``default()``."""
    path = Path(path)
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default()
    empty = default()
    if not isinstance(d, type(empty)):
        return empty
    return migrate(name or path.name, d)


def save(path, d, name: str | None = None, **dumps):
    """Записать атомарно (0600). Словарь — с ``_v`` текущей версии схемы. Вызывать под ``locked(path)``."""
    path = Path(path)
    v = version(name or path.name)
    if isinstance(d, dict) and v:
        d = {VERSION_KEY: v, **{k: x for k, x in d.items() if k != VERSION_KEY}}
    write_private(path, json.dumps(d, **dumps))


def update(path, fn: Callable, default: Callable = dict, name: str | None = None, **dumps):
    """Прочитать → ``fn(данные)`` (меняет на месте) → записать, всё под одним замком. Возвращает результат ``fn``."""
    with locked(path):
        d = load(path, default, name)
        out = fn(d)
        save(path, d, name, **dumps)
        return out
