"""Эталонный прогон всех e2e-сценариев панели — до и после каждого шага разбиения пульта на модули.

    python tests/e2e/run_all.py [--server static|panel] [-j 2] [--only a,b] [--skip a,b] [--shots папка]
                                [--json итог.json]

Поднимает демо-сервер сам (``demo_server.py``, только 127.0.0.1, гасится в конце) и запускает каждый
``tests/e2e/*.py`` отдельным процессом: демо-сценарии получают адрес ``…/?demo`` и папку снимков, «живые»
(``*_live.py``) поднимают свою панель сами и получают только папку снимков. Сценарии сами проходят свои ширины
(390 / 1366) и темы; общая сетка экранов — ``smoke_demo.py``, Mini App — ``miniapp_demo.py``.

Нестабильные сценарии (``FLAKY``) при падении повторяются один раз и помечаются «повтор». Итог — таблица
«сценарий · результат · секунды»; код выхода 1, если что-то упало. Снимки без ``--shots`` — во временной папке,
удаляются в конце (место в /tmp ограничено).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# не сценарии: проверка «N назад» (pytest сравнивает с ago.py сам), инструменты прогона и замера
NOT_SCENARIOS = {"ago_check", "run_all", "measure_load", "demo_server"}
# delete_live — старт своей панели за 15 с не всегда успевает под нагрузкой (рядом pytest)
FLAKY = {"palette_demo", "chat_keeps_place", "stt_stream_demo", "delete_live"}
TIMEOUT = 900


def scenarios() -> list[str]:
    return sorted(p.stem for p in HERE.glob("*.py") if p.stem not in NOT_SCENARIOS and not p.stem.startswith("_"))


def one(name: str, base: str, shots: Path) -> tuple[bool, float, str]:
    d = shots / name
    d.mkdir(parents=True, exist_ok=True)
    args = [str(d)] if name.endswith("_live") else [base, str(d)]
    env = {k: v for k, v in os.environ.items() if k not in ("TMUX", "TMUX_PANE")}
    env["TMUX_TMPDIR"] = tempfile.mkdtemp(prefix="gp-run-", dir="/tmp")
    t = time.time()
    try:
        r = subprocess.run([sys.executable, str(HERE / f"{name}.py"), *args], capture_output=True, text=True,
                           timeout=TIMEOUT, env=env, cwd=str(HERE.parents[1]))
        ok, out = r.returncode == 0, (r.stdout + r.stderr)
    except subprocess.TimeoutExpired as e:
        ok, out = False, f"превышено {TIMEOUT} с\n{e.stdout or ''}{e.stderr or ''}"
    finally:
        shutil.rmtree(env["TMUX_TMPDIR"], ignore_errors=True)
    return ok, time.time() - t, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--server", choices=("static", "panel"), default="static",
                    help="static — python -m http.server в web/; panel — настоящий сервер панели")
    ap.add_argument("-j", type=int, default=2, help="сколько сценариев сразу (у каждого свой Chrome)")
    ap.add_argument("--only", default="", help="через запятую: только эти сценарии")
    ap.add_argument("--skip", default="", help="через запятую: пропустить")
    ap.add_argument("--shots", help="папка снимков (по умолчанию — временная, удаляется)")
    ap.add_argument("--json", help="сохранить итог в JSON")
    a = ap.parse_args(argv)
    names = scenarios()
    if a.only:
        names = [n for n in names if n in a.only.split(",")]
    names = [n for n in names if n not in a.skip.split(",")]
    shots = Path(a.shots) if a.shots else Path(tempfile.mkdtemp(prefix="gp-e2e-", dir="/tmp"))
    from demo_server import demo_server

    res: dict[str, dict] = {}
    t0 = time.time()
    try:
        with demo_server(a.server) as base:
            print(f"сервер демо ({a.server}): {base}; сценариев: {len(names)}", flush=True)

            def job(name: str) -> None:
                ok, sec, out = one(name, base, shots)
                again = False
                if not ok and name in FLAKY:
                    again = True
                    ok, sec2, out = one(name, base, shots)
                    sec += sec2
                res[name] = {"ok": ok, "sec": round(sec, 1), "retry": again,
                             "tail": "" if ok else "\n".join(out.strip().splitlines()[-12:])}
                print(f"{'ok  ' if ok else 'FAIL'} {name} · {sec:.0f} с" + (" · повтор" if again else ""), flush=True)

            with ThreadPoolExecutor(max(1, a.j)) as ex:
                list(ex.map(job, names))
    finally:
        if not a.shots:
            shutil.rmtree(shots, ignore_errors=True)
    bad = [n for n in names if not res.get(n, {}).get("ok")]
    print(f"\nитог: {len(names) - len(bad)}/{len(names)} зелёных за {time.time() - t0:.0f} с"
          + (f"; повторы: {', '.join(n for n in names if res.get(n, {}).get('retry'))}"
             if any(r.get("retry") for r in res.values()) else ""))
    for n in bad:
        print(f"\n--- {n} ---\n{res.get(n, {}).get('tail', 'не запущен')}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
