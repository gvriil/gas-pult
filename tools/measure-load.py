#!/usr/bin/env python3
"""Замер загрузки панели «до/после» (#191): сколько ждёт человек до готовности ввода.

    python tools/measure-load.py [--runs 5] [--json out.json] [--ref прошлый.json] [--md out.md]

Поднимает настоящую панель на 127.0.0.1 (``tests/e2e/focus_live.start``: свой tmux, подставной claude, вход
владельца) — заголовки, сжатие и части как в бою. Сценарии:

- «вход» — обычный вход владельца: до первого полезного экрана — видимой карточки или строки сессии, либо поля
  ввода (телефон после входа сразу открывает последнюю сессию);
- «демо» — ``?demo&home``: до первой карточки (демо с #191 грузит свою часть ``js/demo.js``).

Устройства: телефон 390 (процессор ×4 медленнее, сеть «4G»: 60 мс, 9 Мбит/с) и компьютер 1366 (без замедления).
Каждый прогон — холодный заход (пустой кэш) и сразу повторный (тёплый кэш). Метрики — медиана: до цели (мс),
FCP, работа скриптов (CDP ScriptDuration), байты с своего сервера (сжатые), число запросов. Внешние адреса
(telegram.org) отключены — сеть до них на цифры не влияет.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "e2e"))

PROBE = """(sel) => {
  window.__m = { hit: 0 };
  const ok = () => [...document.querySelectorAll(sel)].some((e) => e.offsetParent !== null);
  const look = () => { if (!window.__m.hit && ok()) window.__m.hit = performance.now(); };
  new MutationObserver(look).observe(document, { childList: true, subtree: true, attributes: true });
}"""
COLLECT = """() => {
  const nav = performance.getEntriesByType("navigation")[0] || {};
  const fcp = performance.getEntriesByName("first-contentful-paint")[0]?.startTime || 0;
  const own = [nav, ...performance.getEntriesByType("resource")]
    .filter((e) => e.name && e.name.startsWith(location.origin));
  return { fcp, hit: window.__m.hit, n: own.length, bytes: own.reduce((a, e) => a + (e.encodedBodySize || 0), 0) };
}"""
DEVICES = {"телефон": dict(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True),
           "компьютер": dict(viewport={"width": 1366, "height": 860})}
KEYS = ("hit", "fcp", "script", "bytes", "n")


def one(ctx, url: str, sel: str, mobile: bool) -> dict:
    pg = ctx.new_page()
    cdp = ctx.new_cdp_session(pg)
    cdp.send("Performance.enable")
    if mobile:
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 60,
                                                      "downloadThroughput": 9e6 / 8, "uploadThroughput": 1.5e6 / 8})
    pg.add_init_script(f"({PROBE})({json.dumps(sel)})")
    pg.goto(url, wait_until="load")
    pg.wait_for_function("() => window.__m.hit > 0", timeout=30000)
    pg.wait_for_timeout(200)
    r = pg.evaluate(COLLECT)
    perf = {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}
    r["script"] = perf.get("ScriptDuration", 0) * 1000
    pg.close()
    return r


def measure(runs: int) -> dict:
    from focus_live import free_port, start
    from playwright.sync_api import sync_playwright

    root = Path(tempfile.mkdtemp(prefix="gp-", dir="/tmp"))
    port, proc = free_port(), None
    try:
        proc, ready = start(root, port)
        base = f"http://127.0.0.1:{port}"
        scenes = {"вход": ("/", ".card[data-id], #navList .nrow, #input", True),
                  "демо": ("/?demo&home", "#sessionsView .card[data-id]", False)}
        res: dict = {}
        with sync_playwright() as p:
            br = p.chromium.launch(args=["--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"])
            for dev, kw in DEVICES.items():
                for scene, (path, sel, login) in scenes.items():
                    for warm in ("холодный", "тёплый"):
                        res[f"{dev} · {scene} · {warm}"] = []
                    for _ in range(runs):
                        ctx = br.new_context(**kw)
                        if login:
                            c = ready["cookie"]
                            ctx.add_cookies([{"name": c["name"], "value": c["value"], "url": base}])
                        for warm in ("холодный", "тёплый"):
                            res[f"{dev} · {scene} · {warm}"].append(one(ctx, base + path, sel, dev == "телефон"))
                        ctx.close()
            br.close()
        return {k: {m: statistics.median(r[m] for r in v) for m in KEYS} for k, v in res.items()}
    finally:
        if proc:
            proc.terminate()
            proc.wait(5)
        subprocess.run(["tmux", "-S", str(root / "s"), "kill-server"], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)


def table(med: dict, ref: dict | None = None) -> str:
    head = ["сценарий", "до готовности, мс", "FCP, мс", "скрипты, мс", "КБ со своего сервера", "запросов"]
    rows = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for k, v in med.items():
        cells = []
        for m in KEYS:
            x = v[m] / 1024 if m == "bytes" else v[m]
            s = f"{x:.1f}" if m == "bytes" else f"{x:.0f}"
            if ref and k in ref:
                y = ref[k][m] / 1024 if m == "bytes" else ref[k][m]
                s = (f"{y:.1f}" if m == "bytes" else f"{y:.0f}") + " → " + s
            cells.append(s)
        rows.append(f"| {k} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--json")
    ap.add_argument("--ref")
    ap.add_argument("--md")
    a = ap.parse_args(argv)
    med = measure(a.runs)
    ref = json.loads(Path(a.ref).read_text(encoding="utf-8")) if a.ref else None
    md = table(med, ref)
    print(md)
    if a.json:
        Path(a.json).write_text(json.dumps(med, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.md:
        Path(a.md).write_text(md + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
