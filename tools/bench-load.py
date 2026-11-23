"""Нагрузка на хранение (разбор архитектуры 23.11, docs/STORAGE.md «Нагрузка»): одновременная запись разных
пространств потоками и процессами и опрос панели по HTTP. Режимы json, dual, sqlite.

Запуск: ``PYTHONPATH=src python tools/bench-load.py [--spaces 40] [--threads 8] [--procs 4] [--ops 50]
[--clients 16] [--reqs 60] [--modes json,dual,sqlite] [--dir <папка на диске>]``. Всё — во временной папке
(данные, config.toml, пространства); боевые данные и службы не трогаются, tmux не вызывается (подделка). Печатает
таблицы Markdown.

1. **Хранилище** — ``threads`` потоков одного процесса, затем ``procs`` процессов; у каждого писателя свои
   пространства (``i % писателей == k``) и ``ops`` операций. Операция — то, что пульт пишет про человека и окно
   пространства:
   - человек — ``People.add(uid, tenant=пространство)`` (people.json);
   - вид панели человека — ``People.set_ui`` (окна, которые он скрыл: ui.json / people.json);
   - вход — ``Auth.issue`` (web_sessions.json);
   - ссылка на окно пространства — ``Focus.new(окно @N, space=пространство)`` (focus.json);
   - задача по окну — ``Tasks.add`` (tasks.json, общий список владельца; в названии — пространство).
   Проверка: дошло ли всё («потеряно» = 0), у каждого человека, ссылки и задачи — своё пространство («не то
   пространство» = 0), вход ведёт к своему человеку; в dual — ``sqlstore.verify`` (JSON = SQLite).
2. **HTTP** — тестовый сервер панели (``webapp.Panel`` + ``ThreadingHTTPServer``, как в tests/test_routes.py) во
   временной папке; ``clients`` клиентов одновременно, по ``reqs`` запросов: типичный опрос (``/api/sessions``,
   ``/api/history``) и запись — владелец ``/api/tasks/add``, человек пространства ``/api/prefs``. Время ответа
   p50/p95/p99 по видам запросов, ошибки (не 200 или обрыв), затем проверка: все задачи на месте, у каждого человека
   его последний язык и прежнее пространство.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

OWNER = 1
BASE = 10_000_000                 # ID людей писателя k: BASE * (k + 2) + j — диапазоны не пересекаются
LANGS = ("ru", "en")


def slug(i: int) -> str:
    return f"sp{i:04d}"


def _env(data: str, m: str):
    os.environ["GAS_PULT_STORAGE"] = m
    os.environ["GAS_PULT_DATA_DIR"] = data


# ---------- 1. хранилище: потоки и процессы ----------

def write_ops(data: str, m: str, k: int, writers: int, spaces: int, ops: int, out: dict | None = None):
    """Писатель ``k``: пространства ``i % writers == k``; ``ops`` операций (человек, вид, вход, ссылка, задача).
    ``out`` — куда положить {токен: uid} (потоки); у процесса — в файл ``tokens-<k>.json`` папки данных."""
    _env(data, m)
    from gas_pult.focus import Focus
    from gas_pult.people import People
    from gas_pult.tasks import Tasks
    from gas_pult.webauth import Auth
    d = Path(data)
    p, f, t, a = People(d / "people.json", [OWNER]), Focus(d / "focus.json"), Tasks(d / "tasks.json"), \
        Auth(d / "web_sessions.json")
    mine = [slug(i) for i in range(spaces) if i % writers == k]
    toks = {}
    for j in range(ops):
        s, uid = mine[j % len(mine)], BASE * (k + 2) + j
        p.add(uid, "member", name=f"w{k}-{j}", tenant=s)
        p.set_ui(uid, {"persona": "developer", "hidden": [f"{s}:@{j}"]})
        toks[a.issue(uid)] = uid
        f.new({"id": f"@{j}", "path": f"/w/{s}", "name": s, "space": s}, by=OWNER, mode="space", ttl=0)
        t.add({"title": f"{s} w{k}-{j}", "next": "проверить", "chat": f"@{j}"})
    if out is not None:
        out.update(toks)
    else:
        (d / f"tokens-{k}.json").write_text(json.dumps(toks))


def check_store(data: str, m: str, writers: int, ops: int, toks: dict) -> dict:
    """Что дошло и куда: потеряно (людей, видов, входов, ссылок, задач), не то пространство, JSON≠SQLite."""
    _env(data, m)
    from gas_pult import sqlstore
    from gas_pult.focus import Focus
    from gas_pult.people import People
    from gas_pult.tasks import Tasks
    from gas_pult.webauth import Auth
    d = Path(data)
    p, f, t, a = People(d / "people.json", [OWNER]), Focus(d / "focus.json"), Tasks(d / "tasks.json"), \
        Auth(d / "web_sessions.json")
    want = writers * ops
    people = {x["id"]: x for x in p.list()}
    lost = wrong = 0
    for k in range(writers):
        for j in range(ops):
            uid = BASE * (k + 2) + j
            rec = people.get(uid)
            if rec is None:
                lost += 1
                continue
            if int(rec.get("tenant", "sp-1")[2:]) % writers != k:
                wrong += 1
            hidden = p.ui(uid).get("hidden") or []
            if not hidden:
                lost += 1
            elif hidden[0].split(":")[0] != rec.get("tenant"):
                wrong += 1
    got_toks = sum(1 for tok, uid in toks.items() if a.uid(tok) == uid)
    lost += want - got_toks
    links = [x for x in f.listing() if x.get("space")]
    lost += want - len(links)
    wrong += sum(1 for x in links if x.get("name") != x.get("space"))
    tasks = t.list()
    lost += want - len(tasks)
    seen = {x["title"] for x in tasks}
    lost += want - len(seen)                                        # задача не записалась дважды вместо другой
    for x in tasks:
        s, who = x["title"].split(" ", 1)
        if int(s[2:]) % writers != int(who[1:].split("-")[0]):
            wrong += 1
    v = (sum(len(r["missing"]) + len(r["extra"]) + len(r["differ"]) for r in sqlstore.verify(d).values())
         if m == "dual" else None)
    return {"want": want * 5, "lost": lost, "wrong": wrong, "verify": v}


def store_threads(m: str, threads: int, spaces: int, ops: int, where: str | None) -> dict:
    with tempfile.TemporaryDirectory(prefix="gp-load-t-", dir=where) as d:
        toks: dict = {}
        errs: list = []

        def run(k):
            try:
                write_ops(d, m, k, threads, spaces, ops, toks)
            except Exception as e:
                errs.append(repr(e))
        ts = [threading.Thread(target=run, args=(k,)) for k in range(threads)]
        t0 = time.perf_counter()
        for x in ts:
            x.start()
        for x in ts:
            x.join()
        sec = time.perf_counter() - t0
        return {**check_store(d, m, threads, ops, toks), "sec": sec, "errors": len(errs), "how": f"потоки: {threads}"}


def store_procs(m: str, procs: int, spaces: int, ops: int, where: str | None) -> dict:
    with tempfile.TemporaryDirectory(prefix="gp-load-p-", dir=where) as d:
        ctx = mp.get_context("spawn")
        ps = [ctx.Process(target=write_ops, args=(d, m, k, procs, spaces, ops)) for k in range(procs)]
        t0 = time.perf_counter()
        for x in ps:
            x.start()
        for x in ps:
            x.join(900)
        sec = time.perf_counter() - t0
        toks = {}
        for k in range(procs):
            try:
                toks.update(json.loads((Path(d) / f"tokens-{k}.json").read_text()))
            except OSError:
                pass
        errs = sum(1 for x in ps if x.exitcode != 0)
        return {**check_store(d, m, procs, ops, toks), "sec": sec, "errors": errs, "how": f"процессы: {procs}"}


# ---------- 2. HTTP: тестовый сервер панели ----------

def fake_tmux(root: Path):
    """tmux без tmux: у владельца и у каждого пространства одно окно ``@1`` с агентом; экран — пустая строка ввода."""
    from gas_pult import tenants
    from gas_pult.tmux import Tmux

    def _windows(self):
        path = f"{self.home}/w" if self.home else str(root / "projects" / "own")
        return [{"id": "@1", "idx": "1", "name": "w", "cmd": "claude", "path": path, "tty": "", "mark": "claude",
                 "by": "", "sid": "", "harness": "claude", "profile": "", "channel": False, "stopped": False}]
    Tmux._windows = _windows
    Tmux.run = lambda self, *a, input=None: "❯ \n"
    tenants.ready = lambda slug, base_root=None, runner=None, now=None: True
    tenants.tmux_of = lambda s, session="main", base_root=None: Tmux("main", home=str(root / "tenants" / s / "home"))


def pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(q / 100 * (len(xs) - 1)))] * 1000


def http_load(m: str, clients: int, reqs: int, spaces: int, where: str | None) -> dict:
    from http.server import ThreadingHTTPServer
    with tempfile.TemporaryDirectory(prefix="gp-load-h-", dir=where) as d:
        root = Path(d)
        _env(str(root / "data"), m)
        os.environ["GAS_PULT_TENANTS_ROOT"] = str(root / "tenants")
        from gas_pult import tenants, webapp, webauth
        from gas_pult.config import Config
        (root / "tenants").mkdir()
        (root / "tenants" / tenants.MARKER).write_text("{}")
        for i in range(spaces):
            (root / "tenants" / slug(i) / "home" / "w").mkdir(parents=True)
            (root / "tenants" / slug(i) / tenants.META).write_text(json.dumps({"title": slug(i)}))
        (root / "projects" / "own").mkdir(parents=True)
        fake_tmux(root)
        p = webapp.Panel(Config(token="1:T", owners=[OWNER], region="NL", session="load",
                                project_roots=[str(root / "projects")]))
        who = [(OWNER, None)] + [(BASE + c, slug(c % spaces)) for c in range(1, clients)]
        for uid, s in who:
            if uid != OWNER:
                p.people.add(uid, "member", f"h{uid}", tenant=s)
            p.people.accept(uid)
            p.people.set_country(uid, chosen="NL")
        toks = {uid: p.auth.issue(uid) for uid, _ in who}
        srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        times: dict[str, list[float]] = {"sessions": [], "history": [], "write": []}
        errs: dict[str, int] = {k: 0 for k in times}
        samples: list[str] = []
        last: dict[int, str] = {}
        owner_writes, alien = [0], [0]
        lock = threading.Lock()

        def req(kind, path, tok, body=None):
            r = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                       {"Cookie": f"{webauth.COOKIE}={tok}", "Content-Type": "application/json"})
            t0, raw = time.perf_counter(), b""
            try:
                with urllib.request.urlopen(r, timeout=60) as x:
                    raw = x.read()
                    ok = x.status == 200
                    why = x.status
            except urllib.error.HTTPError as e:
                ok, why = False, f"{e.code} {e.read()[:200].decode(errors='replace')}"
            except OSError as e:
                ok, why = False, repr(e)
            dt = time.perf_counter() - t0
            with lock:
                times[kind].append(dt)
                if not ok:
                    errs[kind] += 1
                    if len(samples) < 5:
                        samples.append(f"{kind} {path}: {why}")
            return ok, raw

        def client(uid, s):
            tok = toks[uid]
            for i in range(reqs):
                step = i % 4
                if step in (0, 2):
                    ok, raw = req("sessions", "/api/sessions", tok)
                    ids = [x.get("id", "") for x in json.loads(raw).get("sessions", [])] if ok else []
                    if ok and (not ids or (s is not None and any(not x.startswith(f"t:{s}:") for x in ids))):
                        with lock:
                            alien[0] += 1          # своего окна нет или человек пространства увидел чужое
                elif step == 1:
                    wid = "@1" if s is None else f"t:{s}:@1"
                    req("history", "/api/history?w=" + urllib.request.quote(wid, safe=""), tok)
                elif uid == OWNER:
                    if req("write", "/api/tasks/add", tok, {"title": f"нагрузка {i}", "next": "проверить"})[0]:
                        with lock:
                            owner_writes[0] += 1
                else:
                    lang = LANGS[i % len(LANGS)]
                    if req("write", "/api/prefs", tok, {"lang": lang})[0]:
                        last[uid] = lang
        for uid, _ in who:                       # прогрев (не в замере): первый запрос собирает кэши панели
            urllib.request.urlopen(urllib.request.Request(
                base + "/api/sessions", headers={"Cookie": f"{webauth.COOKIE}={toks[uid]}"}), timeout=60).read()
        ts = [threading.Thread(target=client, args=w) for w in who]
        t0 = time.perf_counter()
        for x in ts:
            x.start()
        for x in ts:
            x.join()
        sec = time.perf_counter() - t0
        srv.shutdown()
        lost = owner_writes[0] - len(p.tasks.list())
        lost += sum(1 for uid, lang in last.items() if p.people.prefs(uid).get("lang") != lang)
        wrong = alien[0] + sum(1 for uid, s in who if uid != OWNER and p.people.tenant(uid) != s)
        from gas_pult import sqlstore
        v = (sum(len(r["missing"]) + len(r["extra"]) + len(r["differ"])
                 for r in sqlstore.verify(root / "data").values()) if m == "dual" else None)
        allt = [x for xs in times.values() for x in xs]
        return {"times": times, "all": allt, "errs": errs, "samples": samples, "sec": sec, "lost": lost,
                "wrong": wrong, "verify": v, "n": len(allt)}


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--spaces", type=int, default=40)
    a.add_argument("--threads", type=int, default=8)
    a.add_argument("--procs", type=int, default=4)
    a.add_argument("--ops", type=int, default=50, help="операций на писателя (поток или процесс)")
    a.add_argument("--clients", type=int, default=16, help="клиентов HTTP (первый — владелец)")
    a.add_argument("--reqs", type=int, default=60, help="запросов на клиента")
    a.add_argument("--modes", default="json,dual,sqlite")
    a.add_argument("--skip", default="", help="через запятую: store, http")
    a.add_argument("--dir", help="где создать временные папки (диск, а не tmpfs: важен fsync)")
    args = a.parse_args()
    skip = set(filter(None, args.skip.split(",")))
    with tempfile.TemporaryDirectory(prefix="gp-load-cfg-") as c:
        os.environ["GAS_PULT_CONFIG_DIR"] = c                  # не читать боевой config.toml
        modes = args.modes.split(",")
        print(f"Python {sys.version.split()[0]} · ядер {os.cpu_count()} · {args.spaces} пространств\n")
        if "store" not in skip:
            print(f"Хранилище: {args.ops} операций на писателя × 5 записей (человек, вид, вход, ссылка, задача)\n")
            print("| режим | писатели | записей | потеряно | не то пространство | JSON≠SQLite | ошибок | с |")
            print("|---|---|---|---|---|---|---|---|")
            for m in modes:
                for r in (store_threads(m, args.threads, args.spaces, args.ops, args.dir),
                          store_procs(m, args.procs, args.spaces, args.ops, args.dir)):
                    print(f"| {m} | {r['how']} | {r['want']} | {r['lost']} | {r['wrong']} "
                          f"| {'—' if r['verify'] is None else r['verify']} | {r['errors']} | {r['sec']:.1f} |",
                          flush=True)
        if "http" not in skip:
            print(f"\nHTTP: {args.clients} клиентов × {args.reqs} запросов (опрос /api/sessions, /api/history; запись "
                  "/api/tasks/add владельца, /api/prefs человека пространства)\n")
            print("| режим | запросов | p50, мс | p95, мс | p99, мс | запись p95, мс | опрос p95, мс | ошибок "
                  "| потеряно | не то пространство | JSON≠SQLite | запросов/с |")
            print("|---|---|---|---|---|---|---|---|---|---|---|---|")
            for m in modes:
                r = http_load(m, args.clients, args.reqs, args.spaces, args.dir)
                poll = r["times"]["sessions"] + r["times"]["history"]
                print(f"| {m} | {r['n']} | {pct(r['all'], 50):.1f} | {pct(r['all'], 95):.1f} "
                      f"| {pct(r['all'], 99):.1f} | {pct(r['times']['write'], 95):.1f} | {pct(poll, 95):.1f} "
                      f"| {sum(r['errs'].values())} | {r['lost']} | {r['wrong']} "
                      f"| {'—' if r['verify'] is None else r['verify']} | {r['n'] / r['sec']:.0f} |", flush=True)
                for s in r["samples"]:
                    print(f"  ошибка: {s}", file=sys.stderr)


if __name__ == "__main__":
    main()
