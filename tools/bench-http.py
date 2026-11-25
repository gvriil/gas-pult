"""Замер HTTP панели под нагрузкой: сервер — отдельный процесс, клиенты — другой (в tools/bench-load.py они делили
один процесс Python и одну GIL — время ответа завышалось). Задача портфеля 24.11: p95 при 100 клиентах.

Запуск: ``PYTHONPATH=src python tools/bench-http.py [--clients 16,100] [--reqs 30] [--spaces 40] [--profile]``

Сервер — ``webapp.Panel`` во временной папке, tmux поддельный (tools/bench-load.py: fake_tmux), режим хранения —
``--mode`` (json). Клиент — как в bench-load: половина — ``/api/sessions``, четверть — ``/api/history``, четверть —
запись. ``--profile``: один клиент подряд, cProfile на сервере — цена одного запроса по функциям.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("bench_load", HERE / "bench-load.py")
bl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bl)


def serve(root: Path, mode: str, clients: int, spaces: int, info: Path, profile: str):
    """Процесс сервера: панель, люди, токены → ``info`` (JSON); работает до SIGTERM."""
    from http.server import ThreadingHTTPServer
    bl._env(str(root / "data"), mode)
    os.environ["GAS_PULT_TENANTS_ROOT"] = str(root / "tenants")
    from gas_pult import tenants, webapp
    from gas_pult.config import Config
    (root / "tenants").mkdir()
    (root / "tenants" / tenants.MARKER).write_text("{}")
    for i in range(spaces):
        (root / "tenants" / bl.slug(i) / "home" / "w").mkdir(parents=True)
        (root / "tenants" / bl.slug(i) / tenants.META).write_text(json.dumps({"title": bl.slug(i)}))
    (root / "projects" / "own").mkdir(parents=True)
    bl.fake_tmux(root)
    p = webapp.Panel(Config(token="1:T", owners=[bl.OWNER], region="NL", session="load",
                            project_roots=[str(root / "projects")]))
    who = [(bl.OWNER, None)] + [(bl.BASE + c, bl.slug(c % spaces)) for c in range(1, clients)]
    for uid, s in who:
        if uid != bl.OWNER:
            p.people.add(uid, "member", f"h{uid}", tenant=s)
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    H = webapp.handler(p)
    prof = None
    if profile:
        import cProfile
        prof = cProfile.Profile()
        orig = H.handle

        def handle(self):                    # один клиент подряд — один поток за раз, cProfile не пересекается
            prof.enable()
            try:
                orig(self)
            finally:
                prof.disable()
        H.handle = handle
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    info.write_text(json.dumps({"port": srv.server_address[1], "who": who,
                                "toks": {str(u): p.auth.issue(u) for u, _ in who}}))

    samples: dict = {}
    if os.environ.get("GP_SAMPLE"):                  # опрос стеков всех потоков раз в 5 мс: где ждут под нагрузкой
        import collections
        import traceback
        samples = collections.Counter()

        def sampler():
            me = threading.get_ident()
            while True:
                for tid, fr in sys._current_frames().items():
                    if tid == me:
                        continue
                    st = traceback.extract_stack(fr)
                    own = [f for f in st if "gas_pult" in f.filename]
                    top = st[-1]
                    key = (f"{Path(own[-1].filename).name}:{own[-1].lineno} {own[-1].name}" if own else "-") + \
                        f" → {Path(top.filename).name}:{top.lineno} {top.name}"
                    samples[key] += 1
                time.sleep(0.005)
        threading.Thread(target=sampler, daemon=True).start()

    def stop(*_):
        if prof:
            prof.dump_stats(profile)
        if samples:
            Path(os.environ["GP_SAMPLE"]).write_text(
                "\n".join(f"{n:6d} {k}" for k, n in samples.most_common(40)), encoding="utf-8")
        os._exit(0)
    signal.signal(signal.SIGTERM, stop)
    srv.serve_forever()


def load(base: str, who: list, toks: dict, reqs: int) -> dict:
    from gas_pult import webauth
    times: dict[str, list[float]] = {"sessions": [], "history": [], "write": []}
    errs = [0]
    why: dict[str, int] = {}
    slow: dict[str, int] = {}
    lock = threading.Lock()

    def req(kind, path, tok, body=None):
        r = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                   {"Cookie": f"{webauth.COOKIE}={tok}", "Content-Type": "application/json"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(r, timeout=120) as x:
                x.read()
                ok = x.status == 200
        except OSError as e:
            ok = False
            with lock:
                k = f"{kind} {type(e).__name__}: {str(getattr(e, 'reason', e))[:50]}"
                why[k] = why.get(k, 0) + 1
        dt = time.perf_counter() - t0
        with lock:
            if dt > 2:
                k = f"{kind} {'ok' if ok else 'err'} >{int(dt)}s"
                slow[k] = slow.get(k, 0) + 1
            times[kind].append(dt)
            errs[0] += not ok

    def client(uid, s):
        tok = toks[str(uid)]
        for i in range(reqs):
            step = i % 4
            if step in (0, 2):
                req("sessions", "/api/sessions", tok)
            elif step == 1:
                wid = "@1" if s is None else f"t:{s}:@1"
                req("history", "/api/history?w=" + urllib.request.quote(wid, safe=""), tok)
            elif uid == bl.OWNER:
                req("write", "/api/tasks/add", tok, {"title": f"нагрузка {i}", "next": "проверить"})
            else:
                req("write", "/api/prefs", tok, {"lang": bl.LANGS[i % 2]})
    for uid, _ in who:                                   # прогрев: кэши панели
        req("sessions", "/api/sessions", toks[str(uid)])
    for v in times.values():
        v.clear()
    errs[0] = 0
    ts = [threading.Thread(target=client, args=(u, s)) for u, s in who]
    t0 = time.perf_counter()
    for x in ts:
        x.start()
    for x in ts:
        x.join()
    sec = time.perf_counter() - t0
    allt = [x for v in times.values() for x in v]
    ms = lambda xs, q: round(bl.pct(xs, q)) if xs else None   # noqa: E731 — pct уже в мс
    return {"clients": len(who), "n": len(allt), "errors": errs[0], "rps": round(len(allt) / sec, 1),
            "p50": ms(allt, 50), "p95": ms(allt, 95), "p99": ms(allt, 99),
            **{f"{k}_p95": ms(v, 95) for k, v in times.items()}, "why": why,
            "slow": dict(sorted(slow.items(), key=lambda x: -x[1])[:8])}


def run(clients: int, reqs: int, spaces: int, mode: str, profile: str = "") -> dict:
    with tempfile.TemporaryDirectory(prefix="gp-http-") as d:
        info = Path(d) / "info.json"
        env = dict(os.environ, PYTHONPATH=os.environ.get("PYTHONPATH", "src"))
        cmd = [sys.executable, __file__, "--serve", d, "--mode", mode, "--clients", str(clients),
               "--spaces", str(spaces), "--info", str(info)] + (["--profile-out", profile] if profile else [])
        pr = subprocess.Popen(cmd, env=env)
        try:
            for _ in range(300):
                if info.exists() and info.stat().st_size:
                    break
                time.sleep(0.1)
            i = json.loads(info.read_text())
            return load(f"http://127.0.0.1:{i['port']}", i["who"], i["toks"], reqs)
        finally:
            pr.send_signal(signal.SIGTERM)
            pr.wait(30)


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--clients", default="16,100")
    a.add_argument("--reqs", type=int, default=30)
    a.add_argument("--spaces", type=int, default=40)
    a.add_argument("--mode", default="json")
    a.add_argument("--profile", action="store_true", help="один клиент, cProfile на сервере")
    a.add_argument("--serve"), a.add_argument("--info"), a.add_argument("--profile-out", default="")
    x = a.parse_args()
    if x.serve:
        return serve(Path(x.serve), x.mode, int(x.clients), x.spaces, Path(x.info), x.profile_out)
    if x.profile:
        out = str(Path(tempfile.gettempdir()) / "gp-http.prof")
        r = run(1, x.reqs, x.spaces, x.mode, out)
        import pstats
        print(json.dumps(r, ensure_ascii=False))
        pstats.Stats(out).sort_stats("cumulative").print_stats(25)
        return
    for c in [int(v) for v in x.clients.split(",")]:
        print(json.dumps(run(c, x.reqs, x.spaces, x.mode), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
