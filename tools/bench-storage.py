"""Замер хранения: json (как было) против dual и sqlite (docs/STORAGE.md).

Запуск: ``PYTHONPATH=src python tools/bench-storage.py [--people 1000] [--items 300] [--race 200]
[--dir <папка на диске>]``. Всё — во временной папке, боевые данные и config.toml не трогаются. Печатает таблицы
Markdown.

Люди: ``add`` N людей, ``role`` и ``seen`` каждому. Сессии, фокус-ссылки, задачи: запись (``issue`` / ``new`` /
``add``) и чтение (``uid`` / ``by_cookie`` / ``list``) ``items`` раз. Гонка — 2 процесса × ``race`` записей в один
файл → сколько дошло.
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


def _sessions(path: str, base: int, n: int, m: str):
    os.environ["GAS_PULT_STORAGE"] = m
    from gas_pult.webauth import Auth
    a = Auth(Path(path))
    for i in range(n):
        a.issue(base + i)


def _focus(path: str, base: int, n: int, m: str):
    os.environ["GAS_PULT_STORAGE"] = m
    from gas_pult.focus import Focus
    f = Focus(Path(path))
    for i in range(n):
        f.new({"id": f"@{base + i}", "path": "/x", "name": f"s{i}"}, by=1)


def _tasks(path: str, base: int, n: int, m: str):
    os.environ["GAS_PULT_STORAGE"] = m
    from gas_pult.tasks import Tasks
    t = Tasks(Path(path))
    for i in range(n):
        t.add({"title": f"{base}-{i}", "next": "x"})


def _race(target, path: Path, m: str, race: int) -> float:
    ctx = mp.get_context("spawn")
    ps = [ctx.Process(target=target, args=(str(path), b, race, m)) for b in (100_000, 200_000)]
    t = time.perf_counter()
    for x in ps:
        x.start()
    for x in ps:
        x.join(600)
    return time.perf_counter() - t


def _timed(fn, n: int) -> float:
    t = time.perf_counter()
    for i in range(n):
        fn(i)
    return (time.perf_counter() - t) / n * 1000


def run_modules(m: str, n: int, race: int, where: str | None) -> dict:
    """Сессии, фокус-ссылки, задачи: (запись, чтение, мс) и гонка (дошло, с)."""
    os.environ["GAS_PULT_STORAGE"] = m
    from gas_pult import store, webauth
    from gas_pult.focus import Focus
    from gas_pult.tasks import Tasks
    out = {}
    with tempfile.TemporaryDirectory(prefix="gp-bench-", dir=where) as d:
        a = webauth.Auth(Path(d) / "web_sessions.json")
        toks = []
        w = _timed(lambda i: toks.append(a.issue(1000 + i)), n)
        out["web_sessions"] = (w, _timed(lambda i: a.uid(toks[i]), n))
        f = Focus(Path(d) / "focus.json")
        links = []
        w = _timed(lambda i: links.append(f.new({"id": f"@{i}", "path": "/x", "name": f"s{i}"}, by=1)), n)
        cookies = [f.open(x["token"], "", "bench")[0] for x in links[:50]]
        out["focus"] = (w, _timed(lambda i: f.by_cookie(cookies[i % len(cookies)]), n))
        t = Tasks(Path(d) / "tasks.json")
        w = _timed(lambda i: t.add({"title": f"t{i}", "next": "x"}), n)
        out["tasks"] = (w, _timed(lambda i: t.list(), n))
        for key, name, fn, shape in (("web_sessions", "web_sessions.json", _sessions, dict),
                                     ("focus", "focus.json", _focus, dict), ("tasks", "tasks.json", _tasks, list)):
            g = Path(d) / "race" / name
            sec = _race(fn, g, m, race)
            out[key] += (len(store.load(g, shape)), sec)
    return out


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
    a.add_argument("--items", type=int, default=300, help="операций на модуль: сессии, фокус-ссылки, задачи")
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
        print(f"\nСессии (issue / uid), фокус-ссылки (new / by_cookie), задачи (add / list) · {args.items} операций · "
              f"гонка 2 × {args.race}\n")
        print("| режим | модуль | запись, мс | чтение, мс | гонка: дошло | гонка, с |")
        print("|---|---|---|---|---|---|")
        for m in args.modes.split(","):
            for key, (w, rd, got, sec) in run_modules(m, args.items, args.race, args.dir).items():
                print(f"| {m} | {key} | {w:.2f} | {rd:.2f} | {got} из {2 * args.race} | {sec:.1f} |", flush=True)


if __name__ == "__main__":
    main()
