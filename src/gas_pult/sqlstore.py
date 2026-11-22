"""Служебные данные пульта в SQLite — переход с JSON малыми шагами и с откатом (решение владельца 22.11).

Режим — ключ ``storage`` в config.toml (или переменная ``GAS_PULT_STORAGE``, она важнее):

- ``json`` (по умолчанию) — как раньше: только файлы JSON;
- ``dual`` — источник истины JSON: читаем JSON, пишем в JSON и в SQLite под тем же замком (``store.locked``);
  ошибка SQLite запись JSON не ломает — предупреждение в журнал службы;
- ``sqlite`` — читаем и пишем SQLite, JSON больше не пишется (последний остаётся копией).

Откат — ``storage = "json"`` (или ``gas-pult storage disable``). Ничего не теряется и без команды: запись в режиме
sqlite ставит рядом с JSON отметку ``.<имя>.sqlite-only``; режим json или dual, увидев её, сначала выгружает SQLite в
JSON. Обратно так же: в режиме sqlite JSON, изменённый мимо SQLite (подпись файла «время:размер» не совпала с
запомненной), переносится в SQLite заново.

Переводятся только файлы из ``COLLECTIONS`` — по модулю за PR (люди → сессии → фокус-ссылки → приглашения → задачи
→ события); остальные файлы живут в JSON при любом режиме. Режим общий для всех переведённых модулей: копия, перенос,
отметка «только в SQLite» и выгрузка при откате — по каждому файлу отдельно, поэтому отдельный флаг на модуль не нужен.
Файлы-списки (``tasks.json``) — через ``LISTS``: запись → строка по полю ``id``.

Хранение — одна таблица «ключ-значение по коллекциям»: ``kv(collection, key, json, updated)``. Коллекция — имя
файла (``people.json``), ключ — ключ верхнего уровня (Telegram ID), значение — запись как в JSON. Почему не таблицы
с колонками: файлы пульта — словари записей, и такой вид повторяет их один в один — один код для всех шести модулей
плана, сравнение с JSON (``verify``) — построчно, откат — простая выгрузка; новое поле записи не требует миграции.
Запись — только изменённых строк (сравнение с тем, что в базе). Колонки и индексы для поиска — потом, миграцией
по номеру, когда понадобится запрос, а не чтение всего файла.

База — ``<папка данных>/pult.sqlite3`` (0600), рядом с JSON-файлами коллекции. WAL — читатели не ждут писателя (бот и
панель — разные процессы). ``synchronous=FULL``: каждая запись JSON сейчас делает fsync (``config.write_private``) —
FULL сохраняет ту же гарантию «записано — переживёт отключение питания»; в WAL это один fsync на транзакцию, при
нашей частоте записи (вход, роль, настройки) цена незаметна (замер — docs/STORAGE.md). ``busy_timeout`` — 10 с.
Схема — по номеру ``PRAGMA user_version`` (``SCHEMA``: шаги по порядку).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import sys
import threading
import time
import tomllib
from pathlib import Path

from gas_pult.config import config_dir, write_private

DB_NAME = "pult.sqlite3"
MODES = ("json", "dual", "sqlite")
ENV = "GAS_PULT_STORAGE"
# модуль «люди»: people.json и файлы рядом под его замком (people.py)
PEOPLE = ("people.json", "terms.json", "countries.json", "prefs.json", "emails.json", "tours.json", "ui.json")
SESSIONS = ("web_sessions.json",)           # сессии браузера (webauth.Auth)
FOCUS = ("focus.json",)                     # фокус-ссылки (focus.py)
INVITES = ("invites.json",)                 # приглашения (invites.py)
TASKS = ("tasks.json",)                     # задачи владельца (tasks.py)
COLLECTIONS: tuple[str, ...] = PEOPLE + SESSIONS + FOCUS + INVITES + TASKS
# Файлы-списки (а не словари): запись → строка по полю-ключу; порядок списка при чтении — по ``created``, затем ключу
# (задачи добавляются в конец с ``created`` = время добавления — это и есть порядок файла).
LISTS = {"tasks.json": "id"}
BUSY_MS = 10_000

# Схема по номеру: user_version = число выполненных шагов.
SCHEMA = [
    """CREATE TABLE kv (collection TEXT NOT NULL, key TEXT NOT NULL, json TEXT NOT NULL, updated INTEGER NOT NULL,
                        PRIMARY KEY (collection, key)) WITHOUT ROWID;
       CREATE TABLE collections (name TEXT PRIMARY KEY, version INTEGER NOT NULL DEFAULT 0,
                                 json_sig TEXT NOT NULL DEFAULT '', imported INTEGER NOT NULL DEFAULT 0);
       CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);""",
]


def warn(msg: str):
    """В журнал службы (journalctl) — stderr, как остальной пульт."""
    print(f"storage: {msg}", file=sys.stderr, flush=True)


# ---------- режим ----------

_mode_cache: dict = {"sig": None, "mode": "json"}


def mode() -> str:
    """Текущий режим: переменная ``GAS_PULT_STORAGE``, иначе ``storage`` из config.toml, иначе json. Файл
    настроек читается заново, только если поменялся (время изменения) — службы видят смену без перезапуска."""
    if (env := os.environ.get(ENV, "").strip()):
        return env if env in MODES else "json"
    path = config_dir() / "config.toml"
    try:
        st = path.stat()
        sig = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return "json"
    if _mode_cache["sig"] != sig:
        try:
            m = tomllib.loads(path.read_text(encoding="utf-8")).get("storage", "json")
        except (OSError, tomllib.TOMLDecodeError):
            m = "json"
        _mode_cache.update(sig=sig, mode=m if m in MODES else "json")
    return _mode_cache["mode"]


def mode_for(path) -> str:
    """Режим для файла: не из ``COLLECTIONS`` — всегда json."""
    return mode() if Path(path).name in COLLECTIONS else "json"


def set_config_mode(m: str) -> Path:
    """Записать ``storage = "<m>"`` в config.toml, не трогая остальное (комментарии, порядок, секции)."""
    if m not in MODES:
        raise ValueError(f"режим: {', '.join(MODES)}")
    path = config_dir() / "config.toml"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    line = f'storage = "{m}"'
    for i, x in enumerate(lines):
        if x.split("=", 1)[0].strip() == "storage" and "=" in x:
            lines[i] = line
            break
    else:                                   # до первой секции [..] — иначе TOML отнесёт ключ к секции
        at = next((i for i, x in enumerate(lines) if x.lstrip().startswith("[")), len(lines))
        lines.insert(at, line)
    write_private(path, "\n".join(lines) + "\n")
    _mode_cache["sig"] = None
    return path


# ---------- база ----------

_local = threading.local()


def db_path(data) -> Path:
    return Path(data) / DB_NAME


def _migrate(con: sqlite3.Connection):
    v = con.execute("PRAGMA user_version").fetchone()[0]
    if v >= len(SCHEMA):
        return
    con.execute("BEGIN IMMEDIATE")
    try:
        v = con.execute("PRAGMA user_version").fetchone()[0]     # второй процесс мог успеть раньше
        for i in range(v, len(SCHEMA)):
            for stmt in SCHEMA[i].split(";"):
                if stmt.strip():
                    con.execute(stmt)
            con.execute(f"PRAGMA user_version = {i + 1}")
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise


def connect(data) -> sqlite3.Connection:
    """Соединение с базой папки ``data`` (одно на поток и процесс): 0600, WAL, FULL, busy_timeout, схема."""
    path = db_path(data)
    key = (os.getpid(), str(path))
    cache = getattr(_local, "c", None)
    if cache is None:
        cache = _local.c = {}
    if (con := cache.get(key)) is not None:
        if path.exists():
            return con
        con.close()                         # файл убрали (тесты, ручная очистка) — открыть заново
        del cache[key]
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.exists():
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    con = sqlite3.connect(path, timeout=BUSY_MS / 1000, isolation_level=None)
    con.execute(f"PRAGMA busy_timeout = {BUSY_MS}")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA synchronous = FULL")
    _migrate(con)
    for x in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        with contextlib.suppress(OSError):
            x.chmod(0o600)
    cache[key] = con
    return con


@contextlib.contextmanager
def tx(con: sqlite3.Connection):
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    con.execute("COMMIT")


def json_sig(path) -> str:
    """Подпись файла JSON «время изменения:размер»; нет файла — пусто."""
    try:
        st = Path(path).stat()
    except OSError:
        return ""
    return f"{st.st_mtime_ns}:{st.st_size}"


def _info(con, name: str) -> dict:
    r = con.execute("SELECT version, json_sig, imported FROM collections WHERE name = ?", (name,)).fetchone()
    return {"version": r[0], "json_sig": r[1], "imported": bool(r[2])} if r else \
        {"version": 0, "json_sig": "", "imported": False}


def _set_info(con, name: str, **kw):
    cur = _info(con, name)
    cur.update(kw)
    con.execute("INSERT INTO collections (name, version, json_sig, imported) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET version = excluded.version, json_sig = excluded.json_sig, "
                "imported = excluded.imported", (name, cur["version"], cur["json_sig"], int(cur["imported"])))


def shape(name: str) -> type:
    """Вид файла коллекции: list для ``LISTS``, иначе dict."""
    return list if name in LISTS else dict


def to_rows(name: str, d) -> dict:
    """Данные файла → словарь строк ``kv`` (ключ — строка)."""
    if name in LISTS:
        k = LISTS[name]
        return {str(x[k]): x for x in d if isinstance(x, dict) and x.get(k)}
    return {str(k): v for k, v in d.items()}


def from_rows(name: str, rows: dict):
    """Строки ``kv`` → данные в виде файла."""
    if name in LISTS:
        return sorted(rows.values(), key=lambda x: (x.get("created") or 0, str(x.get(LISTS[name]))))
    return rows


def _dump(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _rows(con, name: str) -> dict[str, str]:
    return dict(con.execute("SELECT key, json FROM kv WHERE collection = ?", (name,)))


def _write(con, name: str, d) -> int:
    """Привести строки коллекции к ``d`` (вид файла): только изменённые, лишние — удалить. Вызывать в транзакции."""
    old, now, n = _rows(con, name), int(time.time()), 0
    for k, v in to_rows(name, d).items():
        s = _dump(v)
        if old.pop(str(k), None) != s:
            con.execute("INSERT INTO kv (collection, key, json, updated) VALUES (?, ?, ?, ?) ON CONFLICT"
                        "(collection, key) DO UPDATE SET json = excluded.json, updated = excluded.updated",
                        (name, str(k), s, now))
            n += 1
    for k in old:
        con.execute("DELETE FROM kv WHERE collection = ? AND key = ?", (name, k))
        n += 1
    return n


def read(path) -> tuple[dict | list, int]:
    """Коллекция файла ``path`` из SQLite: (данные, версия схемы). Не переносилась — сначала перенос из JSON."""
    path = Path(path)
    prepare(path.parent)
    con = connect(path.parent)
    info = _info(con, path.name)
    if not info["imported"] or (info["json_sig"] != json_sig(path) and not marker(path).exists()):
        if info["imported"]:
            warn(f"{path.name}: JSON менялся мимо SQLite (режим json) — переношу его в SQLite заново")
        import_json(path)
        info = _info(con, path.name)
    return from_rows(path.name, {k: json.loads(v) for k, v in _rows(con, path.name).items()}), info["version"]


def write(path, d, version: int, *, sync_sig: bool):
    """Записать коллекцию в SQLite одной транзакцией. ``sync_sig`` — JSON только что записан тем же (режим dual):
    запомнить его подпись как «совпадает с SQLite»."""
    path = Path(path)
    prepare(path.parent)
    con = connect(path.parent)
    with tx(con):
        _write(con, path.name, d)
        kw = {"version": version, "imported": True}
        if sync_sig:
            kw["json_sig"] = json_sig(path)
        _set_info(con, path.name, **kw)


def dual_write(path, d, version: int, sig_before: str):
    """Режим dual: JSON уже записан — догнать SQLite. Ошибка — предупреждение, JSON остаётся источником истины."""
    path = Path(path)
    try:
        prepare(path.parent)
        con = connect(path.parent)
        info = _info(con, path.name)
        if info["imported"] and info["json_sig"] != sig_before:
            warn(f"{path.name}: расхождение — JSON менялся мимо SQLite; SQLite выровнен по JSON")
        write(path, d, version, sync_sig=True)
    except (sqlite3.Error, OSError) as e:
        warn(f"{path.name}: запись в SQLite не удалась ({type(e).__name__}: {e}) — JSON записан")


# ---------- отметка «новое только в SQLite» и выгрузка ----------

def marker(path) -> Path:
    path = Path(path)
    return path.with_name(f".{path.name}.sqlite-only")


def mark_sqlite_only(path):
    m = marker(path)
    if not m.exists():
        write_private(m, "в режиме sqlite JSON не пишется; json/dual сначала выгрузит SQLite сюда\n")


def import_json(path) -> int:
    """JSON → SQLite (коллекция целиком). Возвращает число записей. Вызывать под ``store.locked(path)`` или
    без него — замок берётся здесь."""
    from gas_pult import store
    path = Path(path)
    with store.locked(path):
        d = store.load_json(path, shape(path.name))
        con = connect(path.parent)
        with tx(con):
            _write(con, path.name, d)
            _set_info(con, path.name, version=store.version(path.name), json_sig=json_sig(path), imported=True)
        return len(d)


def export_json(path) -> int:
    """SQLite → JSON (откат): записать JSON из SQLite, снять отметку. Возвращает число записей."""
    from gas_pult import store
    path = Path(path)
    with store.locked(path):
        con = connect(path.parent)
        d = from_rows(path.name, {k: json.loads(v) for k, v in _rows(con, path.name).items()})
        store.save_json(path, d, ensure_ascii=False)
        with tx(con):
            _set_info(con, path.name, json_sig=json_sig(path), imported=True)
        marker(path).unlink(missing_ok=True)
        return len(d)


def heal(path):
    """Режим json или dual, а рядом отметка «новое только в SQLite» — сначала выгрузить SQLite в JSON."""
    if marker(path).exists() and db_path(Path(path).parent).exists():
        warn(f"{Path(path).name}: возврат с режима sqlite — выгружаю SQLite в JSON")
        export_json(path)


# ---------- копия, перенос, сверка ----------

def files(data) -> list[Path]:
    return [Path(data) / n for n in COLLECTIONS]


def _covered(con) -> set[str]:
    """Какие коллекции уже есть в копии JSON. Копия до списка ``backup_set`` (первый PR, «люди») — только PEOPLE."""
    r = con.execute("SELECT v FROM meta WHERE k = 'backup_set'").fetchone()
    if r:
        return set(json.loads(r[0]))
    return set(PEOPLE) if con.execute("SELECT 1 FROM meta WHERE k = 'backup'").fetchone() else set()


def backup(data, force: bool = False) -> Path | None:
    """Копия JSON-файлов коллекций (и их ``.v``) в ``<data>/backup/json-<дата>/`` (0700/0600). Один раз на
    коллекцию: копия уже есть — None; новые коллекции (модуль перевели после первой копии) — ещё одна копия только с
    ними. ``force`` — снять полную копию ещё раз."""
    from gas_pult import store
    data = Path(data)
    with store.locked(db_path(data)):         # бот и панель включаются одновременно — копия всё равно одна
        con = connect(data)
        covered = _covered(con)
        names = list(COLLECTIONS) if force else [n for n in COLLECTIONS if n not in covered]
        if not names:
            return None
        dest = data / "backup" / f"json-{time.strftime('%Y%m%d-%H%M%S')}"
        n = 1
        while dest.exists():
            dest = dest.with_name(f"{dest.name.split('~')[0]}~{n}")
            n += 1
        dest.mkdir(parents=True, mode=0o700)
        for x in (dest, dest.parent):
            x.chmod(0o700)
        for f in (data / n for n in names):
            for src in (f, store.vfile(f)):
                if src.exists():
                    shutil.copyfile(src, dest / src.name)
                    (dest / src.name).chmod(0o600)
        with tx(con):
            for k, v in (("backup", str(dest)), ("backup_set", json.dumps(sorted(covered | set(names))))):
                con.execute("INSERT INTO meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                            (k, v))
        return dest


_ready: set = set()


def prepare(data):
    """Первое обращение к SQLite в режиме dual/sqlite (в том числе флаг поставили руками): копия JSON — один раз."""
    key = (os.getpid(), str(Path(data)))
    if key in _ready:
        return
    if (dest := backup(data)):
        warn(f"копия JSON перед переходом на SQLite: {dest}")
    _ready.add(key)


def verify(data) -> dict[str, dict]:
    """Сравнить JSON и SQLite по каждой коллекции: {имя: {json, sqlite, missing, extra, differ}} — списки ключей."""
    from gas_pult import store
    con = connect(data)
    out = {}
    for f in files(data):
        js = to_rows(f.name, store.load_json(f, shape(f.name)))
        s = {k: json.loads(v) for k, v in _rows(con, f.name).items()}
        out[f.name] = {"json": len(js), "sqlite": len(s),
                       "missing": sorted(set(js) - set(s)), "extra": sorted(set(s) - set(js)),
                       "differ": sorted(k for k in set(js) & set(s) if js[k] != s[k])}
    return out


def status(data) -> dict:
    data = Path(data)
    out = {"mode": mode(), "db": str(db_path(data)), "exists": db_path(data).exists(), "collections": {}}
    if not out["exists"]:
        return out
    con = connect(data)
    out["schema"] = con.execute("PRAGMA user_version").fetchone()[0]
    out["journal"] = con.execute("PRAGMA journal_mode").fetchone()[0]
    out["size"] = db_path(data).stat().st_size
    r = con.execute("SELECT v FROM meta WHERE k = 'backup'").fetchone()
    out["backup"] = r[0] if r else ""
    for f in files(data):
        info = _info(con, f.name)
        n = con.execute("SELECT COUNT(*) FROM kv WHERE collection = ?", (f.name,)).fetchone()[0]
        out["collections"][f.name] = {**info, "rows": n, "json_exists": f.exists(),
                                      "json_in_sync": info["json_sig"] == json_sig(f),
                                      "sqlite_only": marker(f).exists()}
    return out


def enable(data, m: str) -> dict:
    """Включить dual или sqlite: копия JSON (один раз) → перенос JSON в SQLite → ``storage`` в config.toml."""
    if m not in ("dual", "sqlite"):
        raise ValueError("включить можно dual или sqlite")
    data = Path(data)
    first = backup(data)
    _ready.add((os.getpid(), str(data)))
    moved = {}
    for f in files(data):
        if marker(f).exists():               # уже в sqlite: новое — в SQLite, JSON не трогаем
            moved[f.name] = None
            continue
        moved[f.name] = import_json(f)
    if m == "dual":
        for f in files(data):
            if marker(f).exists():
                export_json(f)               # из sqlite обратно в dual: JSON снова источник истины
    set_config_mode(m)
    return {"backup": str(first) if first else "", "imported": moved}


def disable(data) -> dict:
    """Вернуться к JSON: всё новое из SQLite — в JSON, затем ``storage = "json"``."""
    data = Path(data)
    out = {}
    if db_path(data).exists():
        for f in files(data):
            if marker(f).exists():
                out[f.name] = export_json(f)
    set_config_mode("json")
    return {"exported": out}
