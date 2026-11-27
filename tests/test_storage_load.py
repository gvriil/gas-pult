"""Одновременная запись разных пространств (разбор архитектуры 23.11, docs/STORAGE.md «Нагрузка»): потоки и процессы
пишут людей, вид панели (скрытые окна), входы, ссылки на окна и задачи — в режимах json, dual и sqlite. Ничего не
потеряно, у каждой записи своё пространство, в dual JSON и SQLite совпадают (``sqlstore.verify``).

Полный замер с временем ответа панели — ``tools/bench-load.py``.
"""

import multiprocessing
import threading
from pathlib import Path

import pytest

from gas_pult import sqlstore
from gas_pult.focus import Focus
from gas_pult.people import People
from gas_pult.tasks import Tasks
from gas_pult.webauth import Auth

OWNER = 1
BASE = 10_000_000
SPACES = 6


def space(i: int) -> str:
    return f"sp{i:02d}"


def stores(d: Path):
    return (People(d / "people.json", [OWNER]), Focus(d / "focus.json"), Tasks(d / "tasks.json"),
            Auth(d / "web_sessions.json"))


def write(d: Path, k: int, writers: int, ops: int, toks: dict | None = None):
    """Писатель ``k``: только пространства ``i % writers == k``; люди — свой диапазон ID."""
    p, f, t, a = stores(d)
    mine = [space(i) for i in range(SPACES) if i % writers == k]
    for j in range(ops):
        s, uid = mine[j % len(mine)], BASE * (k + 2) + j
        p.add(uid, "member", name=f"w{k}-{j}", tenant=s)
        p.set_ui(uid, {"persona": "developer", "hidden": [f"{s}:@{j}"]})
        tok = a.issue(uid)
        if toks is not None:
            toks[tok] = uid
        f.new({"id": f"@{j}", "path": f"/w/{s}", "name": s, "space": s}, by=OWNER, mode="space", ttl=0)
        t.add({"title": f"{s} w{k}-{j}", "next": "проверить", "chat": f"@{j}"})


def check(d: Path, writers: int, ops: int, toks: dict | None, m: str):
    p, f, t, a = stores(d)
    people = {x["id"]: x for x in p.list()}
    for k in range(writers):
        for j in range(ops):
            uid = BASE * (k + 2) + j
            s = people[uid]["tenant"]                                  # нет человека — KeyError: потерян
            assert int(s[2:]) % writers == k, (uid, s)                 # не то пространство
            assert p.tenant(uid) == s
            assert p.ui(uid)["hidden"] == [f"{s}:@{j}"]
    if toks is not None:
        assert len(toks) == writers * ops
        assert all(a.uid(tok) == uid for tok, uid in toks.items())
    links = [x for x in f.listing() if x.get("space")]
    assert len(links) == writers * ops
    assert all(x["name"] == x["space"] for x in links)
    titles = [x["title"] for x in t.list()]
    assert len(titles) == len(set(titles)) == writers * ops
    for title in titles:
        s, who = title.split(" ", 1)
        assert int(s[2:]) % writers == int(who[1:].split("-")[0]), title
    if m == "dual":
        bad = {n: r for n, r in sqlstore.verify(d).items() if r["missing"] or r["extra"] or r["differ"]}
        assert not bad, bad


@pytest.mark.parametrize("m", sqlstore.MODES)
def test_threads_write_spaces(m, tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_STORAGE", m)
    toks, errs = {}, []

    def run(k):
        try:
            write(tmp_path, k, 4, 12, toks)
        except Exception as e:
            errs.append(e)
    ts = [threading.Thread(target=run, args=(k,)) for k in range(4)]
    for x in ts:
        x.start()
    for x in ts:
        x.join(60)
    assert not errs
    check(tmp_path, 4, 12, toks, m)


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
@pytest.mark.parametrize("m", sqlstore.MODES)
def test_processes_write_spaces(m, tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_STORAGE", m)
    ctx = multiprocessing.get_context("fork")
    ps = [ctx.Process(target=write, args=(tmp_path, k, 3, 8)) for k in range(3)]
    for x in ps:
        x.start()
    for x in ps:
        x.join(60)
    assert [x.exitcode for x in ps] == [0, 0, 0]
    check(tmp_path, 3, 8, None, m)
