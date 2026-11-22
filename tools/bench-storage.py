"""Замер хранения людей: json (как было) против dual и sqlite (docs/STORAGE.md).

Запуск: ``PYTHONPATH=src python tools/bench-storage.py [--people 1000] [--race 200] [--dir <папка на диске>]``.
Всё — во временной папке, боевые данные и config.toml не трогаются. Печатает таблицу Markdown.

На каждый режим: ``add`` N людей, ``role`` и ``seen`` каждому; гонка — 2 процесса × ``race`` записей в один
people.json → сколько дошло.
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import sys
import tempfile
import time
from pathlib import Path


def _writer(path: str, base: int, n: int, m: str):
    os.environ["GAS_PULT_STORAGE"] = m
    from gas_pult.people import People
    p = People(Path(path), [1])
    for i in range(n):
        p.add(base + i, "member", name=f"u{i}")


def run(m: str, n: int, race: int, where: str | None) -> dict:
    os.environ["GAS_PULT_STORAGE"] = m
    from gas_pult.people import People
    out = {}
    with tempfile.TemporaryDirectory(prefix="gp-bench-", dir=where) as d:
        f = Path(d) / "people.json"
        p = People(f, [1])
        for name, fn in (("add", lambda i: p.add(10 + i, "member", name=f"u{i}")),
                         ("role", lambda i: p.role(10 + i)),
                         ("seen", lambda i: p.seen(10 + i, "iPhone"))):
            t = time.perf_counter()
            for i in range(n):
                fn(i)
            out[name] = (time.perf_counter() - t) / n * 1000
        g = Path(d) / "race" / "people.json"
        ctx = mp.get_context("spawn")
        ps = [ctx.Process(target=_writer, args=(str(g), b, race, m)) for b in (100_000, 200_000)]
        t = time.perf_counter()
        for x in ps:
            x.start()
        for x in ps:
            x.join(600)
        out["race_s"] = time.perf_counter() - t
        out["race"] = len([x for x in People(g, [1]).list() if x["role"] != "owner"])
    return out


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--people", type=int, default=1000)
    a.add_argument("--race", type=int, default=200)
    a.add_argument("--modes", default="json,dual,sqlite")
    a.add_argument("--dir", help="где создать временную папку (диск, а не tmpfs: важен fsync)")
    args = a.parse_args()
    with tempfile.TemporaryDirectory(prefix="gp-bench-cfg-") as c:
        os.environ["GAS_PULT_CONFIG_DIR"] = c                  # не читать боевой config.toml
        os.environ["GAS_PULT_DATA_DIR"] = c
        print(f"Python {sys.version.split()[0]} · {args.people} людей · гонка 2 × {args.race}\n")
        print("| режим | add, мс | role, мс | seen, мс | гонка: дошло | гонка, с |")
        print("|---|---|---|---|---|---|")
        for m in args.modes.split(","):
            r = run(m, args.people, args.race, args.dir)
            print(f"| {m} | {r['add']:.2f} | {r['role']:.2f} | {r['seen']:.2f} | {r['race']} из {2 * args.race} "
                  f"| {r['race_s']:.1f} |", flush=True)


if __name__ == "__main__":
    main()
