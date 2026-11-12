"""Замер загрузки панели в демо (Playwright + CDP): эталон до разбиения пульта на модули и сравнение после.

    python tests/e2e/measure_load.py [адрес-демо | --server panel|static] [--runs 7] [--json out.json]
                                     [--ref прошлый.json] [--md out.md]

Без адреса поднимает сервер сам (``demo_server.py``): по умолчанию настоящую панель — заголовки кэша как в бою.

Сценарии: «главная» (``&home`` → первая карточка сессии ``#sessionsView .card[data-id]``) и «сессия» (``&open=@1``
→ первое сообщение ``#content .msg[data-i]``). Устройства: телефон 390 (замедление процессора ×4 и сеть «4G»:
задержка 60 мс, 9 Мбит/с вниз) и компьютер 1366 (без замедления). Каждый прогон — холодный заход (новый профиль,
пустой кэш) и сразу повторный в том же профиле (тёплый кэш). Внешние адреса (telegram.org, cdnjs) подменяются
пустым ответом — сеть до них не влияет на цифры; их число показано отдельно.

Метрики (медиана по прогонам): FCP; время до цели (карточка или сообщение); DOMContentLoaded; load; длинные задачи
(число и «блокировка» — сумма их частей сверх 50 мс, как TBT) до цели; время работы скриптов и всех задач (CDP
Performance.getMetrics: ScriptDuration, TaskDuration); запросы к своему серверу — число и байты (тело в сжатом
виде, encodedBodySize), внешние — число.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from urllib.parse import urlparse

PROBE = """(sel) => {
  window.__m = { long: [], hit: 0 };
  try { new PerformanceObserver((l) => {
      for (const e of l.getEntries()) window.__m.long.push([e.startTime, e.duration]); })
          .observe({ type: "longtask", buffered: true }); } catch (e) {}
  const look = () => { if (!window.__m.hit && document.querySelector(sel)) window.__m.hit = performance.now(); };
  new MutationObserver(look).observe(document, { childList: true, subtree: true, attributes: true });
}"""

COLLECT = """() => {
  const nav = performance.getEntriesByType("navigation")[0] || {};
  const fcp = performance.getEntriesByName("first-contentful-paint")[0]?.startTime || 0;
  const hit = window.__m.hit, long = window.__m.long.filter(([s]) => s <= hit);
  const own = [nav, ...performance.getEntriesByType("resource")]
    .filter((e) => e.name && e.name.startsWith(location.origin));
  return { fcp, hit, dcl: nav.domContentLoadedEventEnd || 0, load: nav.loadEventEnd || 0,
           long_n: long.length, tbt: long.reduce((a, [, d]) => a + Math.max(0, d - 50), 0),
           own_n: own.length, own_bytes: own.reduce((a, e) => a + (e.encodedBodySize || 0), 0),
           own_transfer: own.reduce((a, e) => a + (e.transferSize || 0), 0) };
}"""

SCENES = {"home": ("home", "#sessionsView .card[data-id]"), "chat": ("open=@1&noscroll", "#content .msg[data-i]")}
DEVICES = {"390": dict(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True),
           "1366": dict(viewport={"width": 1366, "height": 860})}
KEYS = ("fcp", "hit", "dcl", "load", "long_n", "tbt", "script", "task", "own_n", "own_bytes", "own_transfer", "ext_n")


def stub(ext: list):
    """Внешний адрес — пустой ответ и запись в ``ext`` (один аргумент: с двумя Playwright передаёт и request)."""
    def handle(route):
        ext.append(route.request.url)
        route.fulfill(status=200, body="", content_type="text/javascript")
    return handle


def one(ctx, url: str, sel: str, mobile: bool, ext: list) -> dict:
    pg = ctx.new_page()
    cdp = ctx.new_cdp_session(pg)
    cdp.send("Performance.enable")
    if mobile:
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 60,
                                                      "downloadThroughput": 9e6 / 8, "uploadThroughput": 1.5e6 / 8})
    pg.add_init_script(f"({PROBE})({json.dumps(sel)})")
    n0 = len(ext)
    pg.goto(url, wait_until="load")
    pg.wait_for_selector(sel, timeout=30000)
    pg.wait_for_function("() => window.__m.hit > 0", timeout=5000)
    pg.wait_for_timeout(300)
    r = pg.evaluate(COLLECT)
    perf = {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}
    r.update(script=perf.get("ScriptDuration", 0) * 1000, task=perf.get("TaskDuration", 0) * 1000, ext_n=len(ext) - n0)
    pg.close()
    return r


def measure(base: str, runs: int = 7) -> dict:
    from playwright.sync_api import sync_playwright

    origin = "{0.scheme}://{0.netloc}".format(urlparse(base))
    sep = "&" if "?" in base else "?"
    res: dict = {}
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        for dev, kw in DEVICES.items():
            for scene, (q, sel) in SCENES.items():
                for warm in ("cold", "warm"):
                    res[f"{dev} {scene} {warm}"] = []
                for _ in range(runs):
                    ctx = br.new_context(**kw)
                    ext: list = []
                    ctx.route(lambda u: not u.startswith(origin), stub(ext))
                    url = f"{base}{sep}{q}&theme=light"
                    for warm in ("cold", "warm"):
                        res[f"{dev} {scene} {warm}"].append(one(ctx, url, sel, dev == "390", ext))
                    ctx.close()
        br.close()
    return {k: {m: statistics.median(r[m] for r in v) for m in KEYS} for k, v in res.items()}


def table(med: dict, ref: dict | None = None) -> str:
    """Markdown: строка — сценарий, столбцы — метрики; при ``ref`` — «было → стало»."""
    head = ["сценарий", "FCP, мс", "до цели, мс", "DCL, мс", "load, мс", "длинных задач", "блокировка, мс",
            "скрипты, мс", "все задачи, мс", "запросов", "КБ (тело)", "КБ (передано)", "внешних"]
    rows = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for k, v in med.items():
        cells = []
        for m in KEYS:
            x = v[m] / 1024 if m in ("own_bytes", "own_transfer") else v[m]
            s = f"{x:.0f}" if m not in ("own_bytes", "own_transfer") else f"{x:.1f}"
            if ref and k in ref:
                y = ref[k][m] / 1024 if m in ("own_bytes", "own_transfer") else ref[k][m]
                s = (f"{y:.1f} → " if m in ("own_bytes", "own_transfer") else f"{y:.0f} → ") + s
            cells.append(s)
        rows.append(f"| {k} | " + " | ".join(cells) + " |")
    return "\n".join(rows)


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("base", nargs="?", help="адрес демо; без него — свой сервер (--server)")
    ap.add_argument("--server", choices=("panel", "static"), default="panel")
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument("--json", help="сохранить медианы в JSON")
    ap.add_argument("--ref", help="JSON прошлого замера — показать «было → стало»")
    ap.add_argument("--md", help="сохранить таблицу Markdown")
    a = ap.parse_args(argv)
    if a.base:
        med = measure(a.base, a.runs)
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from demo_server import demo_server
        with demo_server(a.server) as base:
            med = measure(base, a.runs)
    ref = json.loads(Path(a.ref).read_text(encoding="utf-8")) if a.ref else None
    md = table(med, ref)
    print(md)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(med, f, ensure_ascii=False, indent=1)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(md + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
