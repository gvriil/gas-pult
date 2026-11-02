"""Утренние цифры сети автомоек по филиалам: выручка, загрузка постов, средний чек, доля допродаж — против плана.

Смены: data/shifts.csv — дата, филиал, выручка, чеков, допродажи (₽: детейлинг и доп. услуги), занято_пост_ч.
Филиалы: data/branches.csv — филиал, постов, часов_работы (часов в день). План: data/plan.csv — месяц, филиал,
выручка_день, загрузка_проц, средний_чек, допродажи_проц.
Загрузка = занятые пост-часы / (постов × часов работы). Средний чек = выручка / чеков. Доля допродаж = допродажи /
выручка. Отклонение = (факт − план) / план, в процентах. Только стандартная библиотека.

    python3 branch_kpi.py --day 2026-11-01 [--shifts data/shifts.csv] [--branches data/branches.csv] \\
        [--plan data/plan.csv] [--threshold 5]
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

METRICS = (("выручка", "выручка_день", "₽"), ("загрузка_проц", "загрузка_проц", "%"),
           ("средний_чек", "средний_чек", "₽"), ("допродажи_проц", "допродажи_проц", "%"))


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def num(s: str) -> float:
    return float((s or "0").replace(" ", "").replace(",", "."))


def fact(rows: list[dict], branch: dict) -> dict:
    """Факт по сменам филиала (одна дата или несколько — с начала месяца, средние за день)."""
    rev = sum(num(r["выручка"]) for r in rows)
    checks = sum(num(r["чеков"]) for r in rows)
    busy = sum(num(r["занято_пост_ч"]) for r in rows)
    cap = num(branch["постов"]) * num(branch["часов_работы"]) * len(rows)
    up = sum(num(r["допродажи"]) for r in rows)
    days = len(rows) or 1
    return {"выручка": rev / days, "загрузка_проц": 100 * busy / cap if cap else 0.0,
            "средний_чек": rev / checks if checks else 0.0, "допродажи_проц": 100 * up / rev if rev else 0.0}


def report(shifts: list[dict], branches: list[dict], plan: list[dict], day: str, threshold: float = 5.0) -> dict:
    """→ {"day", "mtd", "top", "missing"}. Строка: филиал, показатель, ед, план, факт, откл_проц."""
    month = day[:7]
    plans = {p["филиал"]: p for p in plan if p["месяц"] == month}
    out: dict[str, list] = {"day": [], "mtd": [], "top": [], "missing": []}
    for b in branches:
        name = b["филиал"]
        today = [r for r in shifts if r["филиал"] == name and r["дата"] == day]
        mtd = [r for r in shifts if r["филиал"] == name and r["дата"][:7] == month and r["дата"] <= day]
        if not today:
            out["missing"].append(name)
        p = plans.get(name)
        for key, rows in (("day", today), ("mtd", mtd)):
            if not rows:
                continue
            f = fact(rows, b)
            for m, pk, unit in METRICS:
                pv = num(p[pk]) if p and p.get(pk) else None
                dev = round(100 * (f[m] - pv) / pv, 1) if pv else None
                out[key].append({"филиал": name, "показатель": m, "ед": unit, "план": pv, "факт": round(f[m], 1),
                                 "откл_проц": dev})
    out["top"] = sorted((r for r in out["day"] if r["откл_проц"] is not None and abs(r["откл_проц"]) >= threshold),
                        key=lambda r: -abs(r["откл_проц"]))[:3]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Утренние цифры по филиалам против плана")
    ap.add_argument("--day", required=True, help="ГГГГ-ММ-ДД — за какой день (обычно вчера)")
    ap.add_argument("--shifts", type=Path, default=Path("data/shifts.csv"))
    ap.add_argument("--branches", type=Path, default=Path("data/branches.csv"))
    ap.add_argument("--plan", type=Path, default=Path("data/plan.csv"))
    ap.add_argument("--threshold", type=float, default=5.0)
    a = ap.parse_args(argv)
    r = report(read(a.shifts), read(a.branches), read(a.plan), a.day, a.threshold)
    w = csv.writer(sys.stdout)
    w.writerow(["период", "филиал", "показатель", "план", "факт", "откл_проц"])
    for key in ("day", "mtd"):
        for x in r[key]:
            w.writerow([key, x["филиал"], x["показатель"], x["план"], x["факт"], x["откл_проц"]])
    for x in r["top"]:
        print(f"Топ: {x['филиал']} · {x['показатель']}: {x['факт']} против {x['план']} ({x['откл_проц']:+} %)",
              file=sys.stderr)
    if r["missing"]:
        print("Нет данных за день: " + ", ".join(r["missing"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
