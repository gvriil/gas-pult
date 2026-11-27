"""sqlstore.py: переход служебных данных с JSON на SQLite — три режима, перенос, сверка, откат, копия, гонка."""

import json
import multiprocessing as mp
import os
import sqlite3
from pathlib import Path

import pytest

from gas_pult import cli, config, sqlstore, store
from gas_pult.people import People

N = 200


@pytest.fixture(autouse=True)
def own_mode(monkeypatch):
    """Эти тесты ставят режим сами — прогон всех тестов в другом режиме (GAS_PULT_TEST_STORAGE) их не касается."""
    monkeypatch.delenv(sqlstore.ENV, raising=False)


@pytest.fixture
def mode(monkeypatch):
    def set_(m):
        monkeypatch.setenv(sqlstore.ENV, m)
    return set_


def _people(tmp_path):
    return People(tmp_path / "people.json", [1])


def _fill(p):
    p.add(2, "member", name="Иван")
    p.add(3, "viewer", name="Мария")
    p.seen(2, "iPhone")
    p.set_prefs(1, lang="en")                   # владелец — в prefs.json рядом
    p.accept(1)                                 # и в terms.json


def test_json_mode_is_default_and_touches_no_sqlite(tmp_path):
    assert sqlstore.mode() == "json"
    p = _people(tmp_path)
    _fill(p)
    assert p.role(2) == "member" and not (tmp_path / sqlstore.DB_NAME).exists()


def test_dual_writes_both_and_verify_is_clean(tmp_path, mode):
    p = _people(tmp_path)
    p.add(5, "member", name="до перехода")
    sqlstore.enable(tmp_path, "dual")            # копия + перенос; режим — в config.toml теста
    assert sqlstore.mode() == "dual"
    _fill(p)
    j = json.loads((tmp_path / "people.json").read_text())
    assert set(j) == {"2", "3", "5"} and j["2"]["last"]["device"] == "iPhone"
    con = sqlstore.connect(tmp_path)
    rows = dict(con.execute("SELECT key, json FROM kv WHERE collection = 'people.json'"))
    assert {k: json.loads(v) for k, v in rows.items()} == j
    assert all(not (r["missing"] or r["extra"] or r["differ"]) for r in sqlstore.verify(tmp_path).values())
    assert oct((tmp_path / sqlstore.DB_NAME).stat().st_mode & 0o777) == "0o600"
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_dual_reads_json_and_warns_on_drift(tmp_path, mode, capsys):
    mode("dual")
    p = _people(tmp_path)
    p.add(2, "member", name="Иван")
    f = tmp_path / "people.json"
    d = json.loads(f.read_text())
    d["9"] = {"role": "viewer", "name": "руками", "username": "", "added": 1}
    f.write_text(json.dumps(d))                  # правка мимо пульта (или старая версия в режиме json)
    assert p.role(9) == "viewer"                 # источник истины — JSON
    p.add(3, "viewer")
    assert "расхождение" in capsys.readouterr().err
    assert not sqlstore.verify(tmp_path)["people.json"]["missing"]


def test_dual_sqlite_failure_keeps_json(tmp_path, mode, monkeypatch, capsys):
    mode("dual")

    def boom(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")
    monkeypatch.setattr(sqlstore, "write", boom)
    p = _people(tmp_path)
    p.add(2, "member", name="Иван")
    assert p.role(2) == "member" and "2" in json.loads((tmp_path / "people.json").read_text())
    assert "не удалась" in capsys.readouterr().err


def test_sqlite_mode_reads_and_writes_only_sqlite(tmp_path, mode):
    p = _people(tmp_path)
    p.add(2, "member", name="Иван")
    f = tmp_path / "people.json"
    before = f.read_text()
    mode("sqlite")
    assert p.role(2) == "member"                 # первое чтение — перенос JSON в SQLite
    p.add(3, "viewer", name="Мария")
    p.set_prefs(3, simple=True)
    assert f.read_text() == before               # JSON больше не пишется — остаётся копией
    assert p.role(3) == "viewer" and p.prefs(3)["simple"] is True
    assert sqlstore.marker(f).exists()
    other = tmp_path / "offer_tg.json"           # файл не из COLLECTIONS — JSON при любом режиме
    with store.locked(other):
        store.save(other, {"a": 1})
    assert json.loads(other.read_text()) == {"a": 1} and store.load(other) == {"a": 1}


def test_rollback_to_json_keeps_everything(tmp_path, mode):
    p = _people(tmp_path)
    mode("sqlite")
    _fill(p)
    p.remove(3)
    mode("json")                                 # откат одним флагом, без команды
    assert [x["id"] for x in p.list()] == [1, 2]
    assert p.prefs(1)["lang"] == "en" and p.accepted(1) and p.role(2) == "member"
    f = tmp_path / "people.json"
    assert set(json.loads(f.read_text())) == {"2"} and not sqlstore.marker(f).exists()
    p.add(4, "member")                           # в json-режиме — снова в JSON
    mode("sqlite")                               # и обратно: изменённый JSON переносится в SQLite заново
    assert p.role(4) == "member" and [x["id"] for x in p.list()] == [1, 2, 4]


def test_disable_command_exports_and_sets_json(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    cfg = config.config_dir() / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('# мои настройки\nowners = [1]\n\n[email]\nhost = "x"\n')
    p = _people(tmp_path)
    cli.main(["storage", "enable", "sqlite"])
    assert sqlstore.mode() == "sqlite"
    p.add(2, "member", name="Иван")
    assert not (tmp_path / "people.json").exists()
    cli.main(["storage", "disable"])
    assert sqlstore.mode() == "json" and p.role(2) == "member"
    assert "2" in json.loads((tmp_path / "people.json").read_text())
    text = cfg.read_text()
    assert text.startswith("# мои настройки") and text.index('storage = "json"') < text.index("[email]")
    cli.main(["storage", "status"])
    cli.main(["storage", "verify"])


def test_backup_once_private(tmp_path):
    p = _people(tmp_path)
    p.add(2, "member", name="Иван")
    p.accept(1)
    r = sqlstore.enable(tmp_path, "dual")
    dest = Path(r["backup"])
    assert dest.parent == tmp_path / "backup" and dest.name.startswith("json-")
    assert {x.name for x in dest.iterdir()} >= {"people.json", "terms.json", ".people.json.v"}
    assert oct(dest.stat().st_mode & 0o777) == "0o700"
    assert all(oct(x.stat().st_mode & 0o777) == "0o600" for x in dest.iterdir())
    assert json.loads((dest / "people.json").read_text())["2"]["name"] == "Иван"
    assert sqlstore.enable(tmp_path, "sqlite")["backup"] == ""      # второй раз — без новой копии
    assert len(list((tmp_path / "backup").iterdir())) == 1


def test_backup_automatic_when_flag_set_by_hand(tmp_path, mode):
    _people(tmp_path).add(2, "member")
    mode("dual")
    _people(tmp_path).add(3, "member")
    assert len(list((tmp_path / "backup").iterdir())) == 1


def test_schema_migrates_by_user_version(tmp_path, monkeypatch):
    db = tmp_path / sqlstore.DB_NAME
    con = sqlstore.connect(tmp_path)
    assert con.execute("PRAGMA user_version").fetchone()[0] == len(sqlstore.SCHEMA) == 1
    con.execute("INSERT INTO kv VALUES ('people.json', '2', '{}', 1)")
    monkeypatch.setattr(sqlstore, "SCHEMA", [*sqlstore.SCHEMA, "CREATE TABLE extra (a TEXT)"])
    con2 = sqlite3.connect(db)
    sqlstore._migrate(con2)
    assert con2.execute("PRAGMA user_version").fetchone()[0] == 2
    assert con2.execute("SELECT COUNT(*) FROM kv").fetchone()[0] == 1      # данные на месте
    sqlstore._migrate(con2)                                                  # повтор — без ошибок
    assert con2.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'extra'").fetchone()[0] == 1


def test_mode_from_config_and_bad_value(monkeypatch):
    cfg = config.config_dir() / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('owners = [1]\nstorage = "dual"\n')
    assert sqlstore.mode() == "dual"
    sqlstore.set_config_mode("sqlite")
    assert sqlstore.mode() == "sqlite" and cfg.read_text().count("storage") == 1
    monkeypatch.setenv(sqlstore.ENV, "nonsense")
    assert sqlstore.mode() == "json"
    with pytest.raises(ValueError):
        sqlstore.set_config_mode("mongo")


def _writer(path: str, base: int):
    p = People(Path(path), [1])
    for i in range(N):
        p.add(base + i, "member", name=f"u{i}")


def test_sqlite_two_processes_lose_nothing(tmp_path, mode):
    mode("sqlite")
    f = tmp_path / "people.json"
    ctx = mp.get_context("spawn")
    ps = [ctx.Process(target=_writer, args=(str(f), base)) for base in (100_000, 200_000)]
    for x in ps:
        x.start()
    for x in ps:
        x.join(120)
        assert x.exitcode == 0
    assert len([p for p in People(f, [1]).list() if p["role"] != "owner"]) == 2 * N
    assert not f.exists() and os.environ[sqlstore.ENV] == "sqlite"


def test_store_version_kept_in_sqlite(tmp_path, mode):
    mode("sqlite")
    _people(tmp_path).add(2, "member")
    info = sqlstore._info(sqlstore.connect(tmp_path), "people.json")
    assert info["version"] == store.version("people.json") and info["imported"]


# ---------- точечное чтение и кэш коллекции (замер «1000 пространств», 22.11) ----------

def _add_one(path: str, uid: int):
    People(Path(path), [1]).add(uid, "viewer", name="из другого процесса")


def test_sqlite_role_reads_one_row(tmp_path, mode, monkeypatch):
    """role/tenant в режиме sqlite — одна строка по ключу, коллекция целиком не читается."""
    mode("sqlite")
    p = _people(tmp_path)
    p.add(2, "member", name="Иван", tenant="sp0001")
    p.accept(2)
    monkeypatch.setattr(sqlstore, "_rows", lambda *a: pytest.fail("прочитана вся коллекция"))
    assert p.role(2) == "member" and p.tenant(2) == "sp0001" and p.role(9) is None
    assert p.accepted(2)


def test_sqlite_cache_sees_other_process(tmp_path, mode):
    """Кэш коллекции не прячет запись другого процесса — ни при чтении, ни при следующей записи."""
    mode("sqlite")
    f = tmp_path / "people.json"
    p = People(f, [1])
    p.add(2, "member")
    assert {x["id"] for x in p.list()} == {1, 2}            # кэш заполнен
    x = mp.get_context("spawn").Process(target=_add_one, args=(str(f), 3))
    x.start()
    x.join(60)
    assert x.exitcode == 0
    assert p.role(3) == "viewer" and {x["id"] for x in p.list()} == {1, 2, 3}
    p.add(4, "member")                                      # своя запись не затирает чужую
    assert {x["id"] for x in People(f, [1]).list()} == {1, 2, 3, 4}


def test_sqlite_write_keeps_value_types(tmp_path, mode):
    """Сравнение «не менялась ли запись» различает 1, 1.0 и True — как текст JSON."""
    mode("sqlite")
    f = tmp_path / "prefs.json"
    for v in (1, True, 1.0, 1, {"a": 1}, {"a": True}):
        store.update(f, lambda d, v=v: d.__setitem__("k", {"v": v}))
        con = sqlstore.connect(tmp_path)
        raw = con.execute("SELECT json FROM kv WHERE collection = 'prefs.json' AND key = 'k'").fetchone()[0]
        assert raw == json.dumps({"v": v}, separators=(",", ":"))
        assert repr(store.load(f)["k"]["v"]) == repr(v)


def test_sqlite_rollback_drops_cache(tmp_path, mode):
    mode("sqlite")
    f = tmp_path / "people.json"
    p = People(f, [1])
    p.add(2, "member")
    with pytest.raises(RuntimeError), store.locked(f), sqlstore.wtx(tmp_path) as con:
        sqlstore._remember(con, f, *sqlstore._write(con, f, {"9": {"role": "member"}}))
        raise RuntimeError("обрыв")
    assert {x["id"] for x in p.list()} == {1, 2} and p.role(9) is None


def _two_files(data: str, base: int):
    for i in range(N // 2):
        store.update(Path(data) / "people.json", lambda d, i=i: d.__setitem__(str(base + i), {"role": "viewer"}))
        store.update(Path(data) / "focus.json", lambda d, i=i: d.__setitem__(f"f{base + i}", {"w": "x"}))


def test_sqlite_two_processes_two_collections_lose_nothing(tmp_path, mode):
    """Разные коллекции одной базы из разных процессов: кэш, верный «пока держим замок файла», ничего не теряет."""
    mode("sqlite")
    ctx = mp.get_context("spawn")
    ps = [ctx.Process(target=_two_files, args=(str(tmp_path), base)) for base in (100_000, 200_000)]
    for x in ps:
        x.start()
    for x in ps:
        x.join(120)
        assert x.exitcode == 0
    assert len(store.load(tmp_path / "people.json")) == N and len(store.load(tmp_path / "focus.json")) == N
