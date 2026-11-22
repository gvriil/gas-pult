"""sqlstore.py, шаги 2–5: сессии браузера, фокус-ссылки, приглашения, задачи — в трёх режимах, откат, копия, гонка.

Общий механизм — tests/test_sqlstore.py (люди). Здесь — то, что у этих модулей своё: список задач (``LISTS``),
свои замки ``webauth`` и ``tasks`` (теперь ``store.locked``), доп. копия JSON для новых коллекций."""

import json
import multiprocessing as mp
import time
from pathlib import Path

import pytest

from gas_pult import focus, invites, sqlstore, tasks, tenants, webauth

MODES = ("json", "dual", "sqlite")
N = 200
W = {"id": "@1", "name": "shop", "path": "/srv/shop", "cmd": "claude"}


@pytest.fixture
def data(monkeypatch, tmp_path):
    """Папка данных (invites.py берёт её из GAS_PULT_DATA_DIR) и демо-пространство для приглашений."""
    monkeypatch.delenv(sqlstore.ENV, raising=False)
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(d))
    root = tmp_path / "tenants"
    monkeypatch.setenv("GAS_PULT_TENANTS_ROOT", str(root))
    (root / "demo").mkdir(parents=True)
    (root / tenants.MARKER).write_text("{}")
    (root / "demo" / tenants.META).write_text(json.dumps({"title": "Демо"}))
    return d


def _work(d: Path) -> dict:
    """По несколько операций каждого модуля; возвращает, что проверить потом."""
    a = webauth.Auth(d / "web_sessions.json")
    keep, gone = a.issue(7, "iPhone"), a.issue(8, "Mac")
    assert a.uid(keep) == 7 and a.touch(keep, time.time() + 25 * 86400)
    a.logout(gone)
    f = focus.Focus(d / "focus.json")
    link = f.new(W, by=1)
    cookie, _ = f.open(link["token"], "", "iPhone · Safari")
    second = f.new(W, by=1)
    f.revoke(second["id"])
    code = invites.create("demo")
    assert invites.redeem(code, 5)["tenant"] == "demo"
    other = invites.create("demo")
    t = tasks.Tasks(d / "tasks.json")
    x = t.add({"title": "первая", "next": "сделать"})
    y = t.add({"title": "вторая", "next": "сделать", "status": "waiting"})
    z = t.add({"title": "третья", "next": "сделать"})
    t.update(x["id"], {"status": "done"})
    t.remove(z["id"])
    return {"keep": keep, "gone": gone, "cookie": cookie, "link": link["id"], "revoked": second["id"],
            "code": code, "other": other, "tasks": [x["id"], y["id"]]}


def _check(d: Path, w: dict):
    a = webauth.Auth(d / "web_sessions.json")
    assert a.uid(w["keep"]) == 7 and a.uid(w["gone"]) is None
    f = focus.Focus(d / "focus.json")
    assert f.by_cookie(w["cookie"])["w"] == "@1"
    assert [x["id"] for x in f.listing()] == [w["link"]]             # отозванная — не в списке
    assert invites.check(w["code"]) is None and invites.check(w["other"])["tenant"] == "demo"
    t = tasks.Tasks(d / "tasks.json")
    assert [x["id"] for x in t.list()] == w["tasks"][::-1]          # «ждёт вас» — первой, выполненная — в конце
    assert [x["id"] for x in t._load()] == w["tasks"]                # порядок файла — порядок добавления


NEW = ("web_sessions.json", "focus.json", "invites.json", "tasks.json")


@pytest.mark.parametrize("m", MODES)
def test_modules_work_in_every_mode(data, monkeypatch, m):
    monkeypatch.setenv(sqlstore.ENV, m)
    w = _work(data)
    _check(data, w)
    if m == "json":
        assert not sqlstore.db_path(data).exists() and all((data / n).exists() for n in NEW)
    elif m == "dual":                                                 # JSON и SQLite совпадают
        r = sqlstore.verify(data)
        assert all(not (r[n]["missing"] or r[n]["extra"] or r[n]["differ"]) and r[n]["sqlite"] for n in NEW)
    else:                                                             # только SQLite: JSON не пишется
        assert not any((data / n).exists() for n in NEW)
        assert all(sqlstore.marker(data / n).exists() for n in NEW)
        st = sqlstore.status(data)["collections"]
        assert all(st[n]["rows"] for n in NEW)
        assert st["tasks.json"]["rows"] == 2                          # строки — по id задачи


def test_tasks_etag_changes_in_sqlite(data, monkeypatch):
    monkeypatch.setenv(sqlstore.ENV, "sqlite")
    t = tasks.Tasks(data / "tasks.json")
    e0 = t.etag()
    x = t.add({"title": "a", "next": "b"})
    e1 = t.etag()
    assert e0 != e1 and e1 == t.etag()
    t.update(x["id"], {"status": "done"})
    assert t.etag() != e1


def test_rollback_one_flag_keeps_everything(data, monkeypatch):
    monkeypatch.setenv(sqlstore.ENV, "sqlite")
    w = _work(data)
    monkeypatch.setenv(sqlstore.ENV, "json")                         # откат одним флагом, без команды
    _check(data, w)
    assert all((data / n).exists() and not sqlstore.marker(data / n).exists() for n in NEW)
    raw = json.loads((data / "tasks.json").read_text())
    assert isinstance(raw, list) and [x["id"] for x in raw] == w["tasks"]
    assert webauth._h(w["keep"]) in json.loads((data / "web_sessions.json").read_text())
    tasks.Tasks(data / "tasks.json").add({"title": "в json", "next": "x"})
    monkeypatch.setenv(sqlstore.ENV, "sqlite")                       # обратно: изменённый JSON — в SQLite заново
    assert len(tasks.Tasks(data / "tasks.json")._load()) == 3


def test_enable_dual_imports_existing_json_and_verify(data, monkeypatch):
    w = _work(data)                                                   # до перехода — json
    r = sqlstore.enable(data, "dual")
    assert all(r["imported"][n] for n in NEW)
    v = sqlstore.verify(data)
    assert all(not (v[n]["missing"] or v[n]["extra"] or v[n]["differ"]) for n in NEW)
    monkeypatch.delenv(sqlstore.ENV, raising=False)
    sqlstore.enable(data, "sqlite")
    _check(data, w)


def test_extra_backup_for_new_collections(data, monkeypatch):
    """Копию сняли в первом PR (только «люди») — при первом включении новых модулей снимается ещё одна, с ними."""
    tasks.Tasks(data / "tasks.json").add({"title": "a", "next": "b"})
    webauth.Auth(data / "web_sessions.json").issue(7)
    con = sqlstore.connect(data)
    con.execute("INSERT INTO meta (k, v) VALUES ('backup', '/старая/копия')")   # как оставил первый PR
    monkeypatch.setenv(sqlstore.ENV, "dual")
    sqlstore._ready.clear()
    tasks.Tasks(data / "tasks.json").list()
    tasks.Tasks(data / "tasks.json").add({"title": "c", "next": "d"})
    copies = list((data / "backup").iterdir())
    assert len(copies) == 1
    names = {x.name for x in copies[0].iterdir()}
    assert {"tasks.json", "web_sessions.json"} <= names and "people.json" not in names
    assert len(json.loads((copies[0] / "tasks.json").read_text())) == 1        # копия — до первой записи
    sqlstore._ready.clear()
    assert sqlstore.backup(data) is None                                         # второй раз — без копии


# ---------- гонка: 2 процесса × N ----------

def _sessions(path: str, base: int):
    a = webauth.Auth(Path(path))
    for i in range(N):
        a.issue(base + i)


def _focus(path: str, base: int):
    f = focus.Focus(Path(path))
    for i in range(N):
        f.new({"id": f"@{base + i}", "path": "/x", "name": f"s{i}"}, by=1)


def _tasks(path: str, base: int):
    t = tasks.Tasks(Path(path))
    for i in range(N):
        t.add({"title": f"{base}-{i}", "next": "x"})


@pytest.mark.parametrize("m", ("dual", "sqlite"))
@pytest.mark.parametrize("name,fn", [("web_sessions.json", _sessions), ("focus.json", _focus),
                                     ("tasks.json", _tasks)])
def test_two_processes_lose_nothing(tmp_path, monkeypatch, m, name, fn):
    monkeypatch.setenv(sqlstore.ENV, m)                              # дочерние процессы (spawn) наследуют режим
    f = tmp_path / name
    ctx = mp.get_context("spawn")
    ps = [ctx.Process(target=fn, args=(str(f), base)) for base in (100_000, 200_000)]
    for x in ps:
        x.start()
    for x in ps:
        x.join(180)
        assert x.exitcode == 0
    from gas_pult import store
    d = store.load(f, sqlstore.shape(name))
    assert len(d) == 2 * N
    if m == "dual":
        assert not sqlstore.verify(tmp_path)[name]["missing"]
