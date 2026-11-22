"""Хранилища JSON пульта: замок, атомарная запись, версия схемы.

Бот и панель — разные процессы и пишут одни файлы (``people.json``, ``focus.json``…). ``threading.Lock`` защищает
только потоки одного процесса: два процесса читали старое, каждый дописывал своё, и второй затирал первого (замер
22.11: 2 процесса × 200 записей в people.json → 229 из 400). Поэтому:

- ``with locked(path):`` — замок потоков (общий на файл в процессе, повторный вход в том же потоке — без ожидания)
  и ``fcntl.flock`` на ``.<файл>.lock`` рядом — тот же замок, что у ``tasks.py`` и ``webauth.py``;
- ``update(path, fn)`` — прочитать → изменить → записать под одним замком;
- запись — ``config.write_private``: 0600, временный файл и ``os.replace`` — обрыв записи файл не портит.

Версия схемы — отдельный файл рядом ``.<файл>.v`` (0600, внутри число); файл данных — в прежнем виде, без служебных
полей, поэтому старая версия пульта читает его без ошибок (откат безопасен). ``MIGRATIONS[имя файла] = [(версия, fn),
…]``: ``load`` применяет все шаги новее версии из ``.v`` (нет файла — версия 0), ``save`` пишет данные, затем версию —
под тем же замком; файл переводится при первой записи. Ключ ``_v`` внутри данных (с ранней сборки этой ветки)
``save`` убирает.

Режим хранения (``sqlstore.py``, ключ ``storage`` в config.toml): для файлов из ``sqlstore.COLLECTIONS`` ``load`` и
``save`` в режиме dual пишут ещё и в SQLite (читают JSON), в режиме sqlite — читают и пишут только SQLite. По
умолчанию json — всё как раньше. Замок ``locked`` — тот же во всех режимах: он держит «прочитать → изменить →
записать» целиком.
"""

from __future__ import annotations

import contextlib
import fcntl
import itertools
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path

from gas_pult import sqlstore
from gas_pult.config import write_private

VERSION_KEY = "_v"                      # ключ версии внутри данных — только с ранней сборки ветки; save его убирает


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
_gen = itertools.count(1)


def hold(path) -> int | None:
    """Номер текущего захвата ``locked(path)`` этим потоком (новый на каждый внешний захват) или None — замок не
    взят. Пока захват длится, файл (и его коллекцию в SQLite) никто другой не пишет — ``sqlstore`` по нему верит
    кэшу коллекции."""
    return (getattr(_held, "g", None) or {}).get(_key(Path(path)))


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
            gens = getattr(_held, "g", None)
            if gens is None:
                gens = _held.g = {}
            gens[key] = next(_gen)
            try:
                yield
            finally:
                gens.pop(key, None)
                depth[key] = 0
                fcntl.flock(fh, fcntl.LOCK_UN)


def vfile(path) -> Path:
    """Файл версии схемы рядом с данными: ``.<имя>.v``."""
    path = Path(path)
    return path.with_name(f".{path.name}.v")


def file_version(path) -> int:
    """Версия схемы, в которой записан файл: число из ``.<имя>.v``; нет файла или мусор — 0."""
    try:
        return max(0, int(vfile(path).read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        return 0


def version(name: str) -> int:
    """Текущая версия схемы файла ``name`` (0 — версий нет, ``_v`` не пишется)."""
    steps = MIGRATIONS.get(name)
    return steps[-1][0] if steps else 0


def migrate(name: str, d, v: int = 0):
    """Привести прочитанное (записанное в версии ``v``) к текущей схеме: все шаги новее ``v``."""
    for ver, fn in MIGRATIONS.get(name, ()):
        if ver > v:
            d = fn(d)
    return d


def load(path, default: Callable = dict, name: str | None = None):
    """Прочитать файл: нет, битый или не того вида (не ``type(default())``) — ``default()``."""
    path = Path(path)
    m = sqlstore.mode_for(path)
    if m == "sqlite" and default is sqlstore.shape(path.name):
        d, v = sqlstore.read(path)
        return migrate(name or path.name, d, v)
    if path.name in sqlstore.COLLECTIONS and sqlstore.marker(path).exists():   # возврат с sqlite: выгрузить в JSON
        sqlstore.heal(path)
    return load_json(path, default, name)


def get(path, key, name: str | None = None):
    """Одна запись файла-словаря по ключу верхнего уровня (нет — None). В режиме sqlite — одна строка базы по ключу
    (``sqlstore.get``), без чтения коллекции; в json и dual — как ``load(path).get(key)``. Записано в старой версии
    схемы — через ``load`` (миграции — на весь файл)."""
    path = Path(path)
    if sqlstore.mode_for(path) == "sqlite" and sqlstore.shape(path.name) is dict:
        s, v = sqlstore.get(path, str(key))
        if v >= version(name or path.name):
            return json.loads(s) if s is not None else None
    return load(path, dict, name).get(str(key))


def load_json(path, default: Callable = dict, name: str | None = None):
    """Только JSON-файл (без режима хранения)."""
    path = Path(path)
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default()
    empty = default()
    if not isinstance(d, type(empty)):
        return empty
    return migrate(name or path.name, d, file_version(path))


def save(path, d, name: str | None = None, **dumps):
    """Записать атомарно (0600): данные, затем версию схемы в ``.<имя>.v``. Вызывать под ``locked(path)``.
    Режим dual — ещё и в SQLite; sqlite — только в SQLite (``sqlstore.py``)."""
    path = Path(path)
    m = sqlstore.mode_for(path) if isinstance(d, sqlstore.shape(path.name)) else "json"
    if isinstance(d, dict) and VERSION_KEY in d:
        d = {k: x for k, x in d.items() if k != VERSION_KEY}
    if m == "sqlite":
        sqlstore.write(path, d, version(name or path.name), sync_sig=False)
        sqlstore.mark_sqlite_only(path)
        return
    sig = ""
    if m == "dual":
        sig = sqlstore.json_sig(path)
        try:                                # копия JSON — до первой записи в режиме dual, а не после
            sqlstore.prepare(path.parent)
        except (OSError, sqlstore.sqlite3.Error) as e:
            sqlstore.warn(f"{path.name}: копия JSON не снята ({type(e).__name__}: {e})")
    save_json(path, d, name, **dumps)
    if m == "dual":
        sqlstore.dual_write(path, d, version(name or path.name), sig)


def save_json(path, d, name: str | None = None, **dumps):
    """Только JSON-файл (без режима хранения)."""
    path = Path(path)
    if isinstance(d, dict) and VERSION_KEY in d:
        d = {k: x for k, x in d.items() if k != VERSION_KEY}
    write_private(path, json.dumps(d, **dumps))
    if (v := version(name or path.name)) and file_version(path) != v:
        write_private(vfile(path), f"{v}\n")


def update(path, fn: Callable, default: Callable = dict, name: str | None = None, **dumps):
    """Прочитать → ``fn(данные)`` (меняет на месте) → записать, всё под одним замком. Возвращает результат ``fn``."""
    with locked(path):
        d = load(path, default, name)
        out = fn(d)
        save(path, d, name, **dumps)
        return out
