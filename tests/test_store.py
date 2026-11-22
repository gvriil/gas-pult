"""store.py: бот и панель — разные процессы; запись в одно хранилище JSON не теряет ничьих изменений.

До store.py (замер 22.11): people.json, 2 процесса × 200 записей → 229 из 400."""

import json
import multiprocessing as mp
import os
import threading
from pathlib import Path

import pytest

from gas_pult import store
from gas_pult.focus import Focus
from gas_pult.people import People

N = 200


def _people_writer(path: str, base: int):
    p = People(Path(path), [1])
    for i in range(N):
        p.add(base + i, "member", name=f"u{i}")


def _focus_writer(path: str, base: int):
    f = Focus(Path(path))
    for i in range(N):
        f.new({"id": f"@{base + i}", "path": "/x", "name": f"s{i}"}, by=1)


def _race(fn, path):
    ctx = mp.get_context("spawn")                 # чистый процесс, как отдельные бот и панель
    ps = [ctx.Process(target=fn, args=(str(path), base)) for base in (100_000, 200_000)]
    for x in ps:
        x.start()
    for x in ps:
        x.join(120)
        assert x.exitcode == 0


def test_people_two_processes_lose_nothing(tmp_path):
    f = tmp_path / "people.json"
    _race(_people_writer, f)
    got = [p for p in People(f, [1]).list() if p["role"] != "owner"]
    assert len(got) == 2 * N
    assert json.loads(f.read_text())["_v"] == store.version("people.json")


def test_focus_two_processes_lose_nothing(tmp_path):
    f = tmp_path / "focus.json"
    _race(_focus_writer, f)
    focus = Focus(f)
    assert len(focus._load()) == 2 * N
    assert len(focus.listing()) == 2 * N and all("_v" not in x["id"] for x in focus.listing())


def test_threads_of_one_process_share_the_lock(tmp_path):
    """Два экземпляра People в одном процессе (бот создаёт свой, панель — свой) — один замок на файл."""
    f = tmp_path / "people.json"
    a, b = People(f, [1]), People(f, [1])
    ts = [threading.Thread(target=lambda p=p, base=base: [p.add(base + i, "viewer") for i in range(50)])
          for p, base in ((a, 1000), (b, 2000))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(a.list()) == 1 + 100


def test_old_file_without_version_reads_and_migrates_on_write(tmp_path):
    f = tmp_path / "people.json"
    f.write_text(json.dumps({"2": {"role": "member", "name": "Иван", "username": "", "added": 1}}))
    p = People(f, [1])
    assert p.role(2) == "member" and [x["id"] for x in p.list()] == [1, 2]   # старый вид читается как есть
    assert "_v" not in f.read_text()                                      # чтение файл не трогает
    p.seen(2, "iPhone")
    d = json.loads(f.read_text())
    assert d["_v"] == 1 and d["2"]["name"] == "Иван" and d["2"]["last"]["device"] == "iPhone"
    assert [x["id"] for x in p.list()] == [1, 2]                         # «_v» наружу не выходит


def test_migration_steps_apply_in_order(tmp_path, monkeypatch):
    monkeypatch.setitem(store.MIGRATIONS, "demo.json", [
        (1, lambda d: d),
        (2, lambda d: {k: {**v, "kind": v.get("kind", "person")} for k, v in d.items()}),
    ])
    f = tmp_path / "demo.json"
    f.write_text(json.dumps({"_v": 1, "a": {"n": 1}}))
    assert store.load(f) == {"a": {"n": 1, "kind": "person"}}
    store.update(f, lambda d: d.update(b={"n": 2}))
    assert json.loads(f.read_text()) == {"_v": 2, "a": {"n": 1, "kind": "person"}, "b": {"n": 2}}
    f.write_text(json.dumps({"_v": 2, "a": {"n": 1}}))                   # уже новая версия — шаги не повторяются
    assert store.load(f) == {"a": {"n": 1}}


def test_unversioned_file_has_no_version_field(tmp_path):
    f = tmp_path / "space.json"                       # имени нет в MIGRATIONS — пишется как раньше, без «_v»
    store.update(f, lambda d: d.update(x=1))
    assert json.loads(f.read_text()) == {"x": 1}
    assert store.load(tmp_path / "nope.json") == {} and store.load(f, list) == []   # нет файла, чужой вид


def test_interrupted_write_keeps_old_file(tmp_path, monkeypatch):
    f = tmp_path / "people.json"
    p = People(f, [1])
    p.add(2, "member", name="Иван")
    before = f.read_bytes()

    def boom(fd):
        raise OSError("диск отвалился")
    monkeypatch.setattr(os, "fsync", boom)            # обрыв посреди записи временного файла
    with pytest.raises(OSError):
        p.add(3, "viewer")
    assert f.read_bytes() == before                   # старый файл цел
    assert [x.name for x in tmp_path.iterdir() if x.name.endswith(".tmp")] == []   # временный убран
    assert oct(f.stat().st_mode & 0o777) == "0o600"


def test_nested_lock_same_thread_does_not_deadlock(tmp_path):
    f = tmp_path / "x.json"
    with store.locked(f), store.locked(f):
        store.save(f, {"a": 1})
    assert store.update(f, lambda d: d.setdefault("b", 2)) == 2
