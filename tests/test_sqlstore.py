"""sqlstore.py: переход служебных данных с JSON на SQLite — три режима, перенос, сверка, откат, копия, гонка."""

import json
import multiprocessing as mp
import os
import sqlite3
from pathlib import Path

import pytest

from gas_pult import cli, config, sqlstore, store
from gas_pult.focus import Focus
from gas_pult.people import People

N = 200


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
    other = tmp_path / "focus.json"              # модуль ещё не переведён — JSON при любом режиме
    Focus(other).new({"id": "@1", "path": "/x", "name": "чат"}, by=1)
    assert len(json.loads(other.read_text())) == 1


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
