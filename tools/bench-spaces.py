"""Замер «1000 пространств» (разбор архитектуры 22.11, docs/STORAGE.md): люди всех пространств — в одном people.json
(поле ``tenant``), ссылки на пространства — в focus.json, приглашения — в invites.json. Режимы json, dual, sqlite.

Запуск: ``PYTHONPATH=src python tools/bench-spaces.py [--spaces 1000] [--race 200] [--procs 4] [--dir <папка>]``.
Всё — во временной папке; боевые данные и config.toml не трогаются. Печатает таблицы Markdown.

Что меряем (среднее на операцию, мс):
- запись при заполнении: ``People.add`` (2–3 человека на пространство), ``Focus.new`` (ссылка на пространство),
  ``invites.new`` (приглашение в пространство);
- чтение: ``role(uid)`` и ``tenant(uid)`` — на каждый запрос панели; «люди пространства» — ``list()`` с отбором по
  ``tenant``; ``Focus.listing()``, ``invites.listing()`` — списки в настройках;
- одновременная запись: ``procs`` процессов, у каждого свои пространства, по ``race`` операций (операция — человек,
  ссылка и приглашение в его пространство) → сколько дошло, у всех ли людей верное пространство, расхождения JSON и
  SQLite (``sqlstore.verify``) в dual;
- размер people.json, focus.json, invites.json, pult.sqlite3 и его -wal (после гонки, без checkpoint).
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import random
import sys
import tempfile
import time
from pathlib import Path

OWNER = 1
BASE_UID = 10_000_000


def slug(i: int) -> str:
    return f"sp{i:04d}"


def _env(data: str, m: str):
    os.environ["GAS_PULT_STORAGE"] = m
    os.environ["GAS_PULT_DATA_DIR"] = data


def _writer(data: str, m: str, k: int, procs: int, spaces: int, n: int):
    """Процесс ``k``: только пространства с номером ``i % procs == k``; люди — свой диапазон ID."""
    _env(data, m)
    from gas_pult import invites
    from gas_pult.focus import Focus
    from gas_pult.people import People
    p, f = People(Path(data) / "people.json", [OWNER]), Focus(Path(data) / "focus.json")
    mine = [slug(i) for i in range(spaces) if i % procs == k]
    for j in range(n):
        s = mine[j % len(mine)]
        p.add(BASE_UID * (k + 2) + j, "member", name=f"race{k}-{j}", tenant=s)
        f.new({"id": "", "path": "/x", "name": s, "space": s}, by=OWNER, mode="space", ttl=0)
        invites.new(s, "member", by=OWNER)


def _timed(fn, n: int) -> float:
    t = time.perf_counter()
    for i in range(n):
        fn(i)
    return (time.perf_counter() - t) / max(n, 1) * 1000


def size(path: Path) -> int:
    return sum(x.stat().st_size for x in path.parent.glob(path.name + "*") if x.is_file())


def run(m: str, spaces: int, race: int, procs: int, where: str | None) -> dict:
    with tempfile.TemporaryDirectory(prefix="gp-bench-spaces-", dir=where) as d:
        _env(d, m)
        from gas_pult import invites, sqlstore
        from gas_pult.focus import Focus
        from gas_pult.people import People
        p, f = People(Path(d) / "people.json", [OWNER]), Focus(Path(d) / "focus.json")
        uids = []                                          # (uid, пространство)
        for i in range(spaces):
            uids += [(BASE_UID + i * 10 + j, slug(i)) for j in range(2 + i % 2)]   # 2 или 3 человека
        out = {"people": len(uids)}
        out["w_people"] = _timed(lambda i: p.add(uids[i][0], "member", name=f"u{i}", tenant=uids[i][1]), len(uids))
        out["w_focus"] = _timed(lambda i: f.new({"id": "", "path": "/x", "name": slug(i), "space": slug(i)},
                                                by=OWNER, mode="space", ttl=0), spaces)
        out["w_invite"] = _timed(lambda i: invites.new(slug(i), "member", by=OWNER), spaces)
        rnd = random.Random(1)
        pick = [rnd.choice(uids) for _ in range(1000)]
        out["role"] = _timed(lambda i: p.role(pick[i][0]), len(pick))
        out["tenant"] = _timed(lambda i: p.tenant(pick[i][0]), len(pick))
        assert all(p.tenant(u) == s for u, s in pick)
        out["space_people"] = _timed(lambda i: [x for x in p.list() if x.get("tenant") == pick[i][1]], 100)
        out["focus_list"] = _timed(lambda i: f.listing(), 100)
        out["invite_list"] = _timed(lambda i: invites.listing(), 100)
        n0, f0, i0 = len(p.list()), len(f.listing()), len(invites.listing())
        ctx = mp.get_context("spawn")
        ps = [ctx.Process(target=_writer, args=(d, m, k, procs, spaces, race)) for k in range(procs)]
        t = time.perf_counter()
        for x in ps:
            x.start()
        for x in ps:
            x.join(900)
        out["race_s"] = time.perf_counter() - t
        _env(d, m)
        got = {x["id"]: x.get("tenant") for x in p.list()}
        new = {u: s for u, s in got.items() if u >= 2 * BASE_UID}
        out["race_people"] = len(got) - n0
        out["race_wrong"] = sum(1 for u, s in new.items() if int(s[2:]) % procs != u // BASE_UID - 2)
        out["race_focus"] = len(f.listing()) - f0
        out["race_invites"] = len(invites.listing()) - i0
        out["race_want"] = procs * race
        out["verify"] = (sum(len(v["missing"]) + len(v["extra"]) + len(v["differ"])
                             for v in sqlstore.verify(Path(d)).values()) if m == "dual" else None)
        out["size_people"] = size(Path(d) / "people.json")
        out["size_focus"] = size(Path(d) / "focus.json")
        out["size_invites"] = size(Path(d) / "invites.json")
        db = Path(d) / sqlstore.DB_NAME
        out["size_db"] = db.stat().st_size if db.exists() else 0
        out["size_wal"] = size(db) - out["size_db"] if db.exists() else 0
    return out


def kb(n: int) -> str:
    return f"{n / 1024:.0f}" if n else "—"


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--spaces", type=int, default=1000)
    a.add_argument("--race", type=int, default=200, help="операций на процесс")
    a.add_argument("--procs", type=int, default=4)
    a.add_argument("--modes", default="json,dual,sqlite")
    a.add_argument("--dir", help="где создать временную папку (диск, а не tmpfs: важен fsync)")
    args = a.parse_args()
    with tempfile.TemporaryDirectory(prefix="gp-bench-cfg-") as c:
        os.environ["GAS_PULT_CONFIG_DIR"] = c                  # не читать боевой config.toml
        rows = {m: run(m, args.spaces, args.race, args.procs, args.dir) for m in args.modes.split(",")}
    r0 = next(iter(rows.values()))
    print(f"Python {sys.version.split()[0]} · {args.spaces} пространств · {r0['people']} людей · "
          f"гонка {args.procs} × {args.race}\n")
    print("| режим | people.add, мс | Focus.new, мс | invites.new, мс | role, мс | tenant, мс | люди пространства, мс "
          "| ссылки, мс | приглашения, мс |")
    print("|---|---|---|---|---|---|---|---|---|")
    for m, r in rows.items():
        print(f"| {m} | {r['w_people']:.2f} | {r['w_focus']:.2f} | {r['w_invite']:.2f} | {r['role']:.2f} "
              f"| {r['tenant']:.2f} | {r['space_people']:.2f} | {r['focus_list']:.2f} | {r['invite_list']:.2f} |")
    print("\n| режим | гонка: люди | ссылки | приглашения | не то пространство | JSON≠SQLite | гонка, с "
          "| people.json, КБ | focus.json, КБ | invites.json, КБ | pult.sqlite3, КБ | -wal, КБ |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for m, r in rows.items():
        want = r["race_want"]
        print(f"| {m} | {r['race_people']} из {want} | {r['race_focus']} из {want} | {r['race_invites']} из {want} "
              f"| {r['race_wrong']} | {'—' if r['verify'] is None else r['verify']} | {r['race_s']:.1f} "
              f"| {kb(r['size_people'])} | {kb(r['size_focus'])} | {kb(r['size_invites'])} | {kb(r['size_db'])} "
              f"| {kb(r['size_wal'])} |")


if __name__ == "__main__":
    main()
