"""Утренние цифры фитнес-клуба по филиалам: продажи новых карт и продления против плана (за день и с начала месяца),
загрузка групповых занятий (записано / вместимость), топ отклонений. Только стандартная библиотека.

Продажи: data/sales.csv — дата, филиал, вид (новая | продление), карт, сумма. План: data/plan.csv — месяц, филиал,
новые_карт, продления_карт, выручка (на месяц). Занятия: data/classes.csv — дата, филиал, время, занятие, записано,
вместимость. План дня = план месяца / дней в месяце; с начала месяца — план дня × номер дня.

    python3 club_kpi.py --day 2026-11-01 [--sales data/sales.csv] [--plan data/plan.csv] \\
        [--classes data/classes.csv] [--threshold 10] [--low 40] [--high 95]
"""

from __future__ import annotations

import argparse
import calendar
import csv
import sys
from datetime import date
from pathlib import Path

METRICS = (("новые_карт", "шт"), ("продления_карт", "шт"), ("выручка", "₽"))


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def num(s: str) -> float:
    return float((s or "0").replace(" ", "").replace(",", "."))


def facts(rows: list[dict]) -> dict[str, float]:
    return {"новые_карт": sum(num(r["карт"]) for r in rows if r["вид"] == "новая"),
            "продления_карт": sum(num(r["карт"]) for r in rows if r["вид"] == "продление"),
            "выручка": sum(num(r["сумма"]) for r in rows)}


def report(sales: list[dict], plan: list[dict], classes: list[dict], day: str, threshold: float = 10,
           low: float = 40, high: float = 95) -> dict:
    """→ {"day", "mtd", "load", "full", "empty", "top", "no_classes"}."""
    d = date.fromisoformat(day)
    month, ndays = day[:7], calendar.monthrange(d.year, d.month)[1]
    plans = {p["филиал"]: p for p in plan if p["месяц"] == month}
    branches = list(dict.fromkeys([*plans, *(s["филиал"] for s in sales if s["дата"][:7] == month)]))
    out: dict = {"day": [], "mtd": [], "load": [], "full": [], "empty": [], "top": [], "no_classes": []}
    for b in branches:
        p = plans.get(b)
        for key, rows, k in (("day", [s for s in sales if s["филиал"] == b and s["дата"] == day], 1),
                             ("mtd", [s for s in sales if s["филиал"] == b and s["дата"][:7] == month
                                      and s["дата"] <= day], d.day)):
            f = facts(rows)
            for m, unit in METRICS:
                pv = round(num(p[m]) / ndays * k, 1) if p and p.get(m) else None
                dev = round(100 * (f[m] - pv) / pv, 1) if pv else None
                out[key].append({"филиал": b, "показатель": m, "ед": unit, "план": pv, "факт": round(f[m], 1),
                                 "откл_проц": dev})
        cl = [c for c in classes if c["филиал"] == b and c["дата"] == day]
        if not cl:
            out["no_classes"].append(b)
            continue
        cap = sum(num(c["вместимость"]) for c in cl)
        out["load"].append({"филиал": b, "занятий": len(cl), "записано": int(sum(num(c["записано"]) for c in cl)),
                            "мест": int(cap), "загрузка_проц": round(100 * sum(num(c["записано"]) for c in cl) / cap, 1)
                            if cap else 0.0})
        for c in cl:
            pct = round(100 * num(c["записано"]) / num(c["вместимость"]), 1) if num(c["вместимость"]) else 0.0
            row = {"филиал": b, "время": c["время"], "занятие": c["занятие"], "загрузка_проц": pct}
            if pct >= high:
                out["full"].append(row)
            elif pct < low:
                out["empty"].append(row)
    # Продажи по дням неровные — топ по месяцу с начала, а не по одному дню.
    out["top"] = sorted((r for r in out["mtd"] if r["откл_проц"] is not None and abs(r["откл_проц"]) >= threshold),
                        key=lambda r: -abs(r["откл_проц"]))[:3]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Утренние цифры фитнес-клуба против плана")
    ap.add_argument("--day", required=True, help="ГГГГ-ММ-ДД — за какой день (обычно вчера)")
    ap.add_argument("--sales", type=Path, default=Path("data/sales.csv"))
    ap.add_argument("--plan", type=Path, default=Path("data/plan.csv"))
    ap.add_argument("--classes", type=Path, default=Path("data/classes.csv"))
    ap.add_argument("--threshold", type=float, default=10)
    ap.add_argument("--low", type=float, default=40)
    ap.add_argument("--high", type=float, default=95)
    a = ap.parse_args(argv)
    r = report(read(a.sales), read(a.plan), read(a.classes), a.day, a.threshold, a.low, a.high)
    w = csv.writer(sys.stdout)
    w.writerow(["период", "филиал", "показатель", "план", "факт", "откл_проц"])
    for key in ("day", "mtd"):
        for x in r[key]:
            w.writerow([key, x["филиал"], x["показатель"], x["план"], x["факт"], x["откл_проц"]])
    for x in r["load"]:
        w.writerow(["загрузка", x["филиал"], "группы", x["мест"], x["записано"], x["загрузка_проц"]])
    for x in r["top"]:
        print(f"Топ: {x['филиал']} · {x['показатель']}: {x['факт']} против {x['план']} ({x['откл_проц']:+} %)",
              file=sys.stderr)
    for x in r["full"]:
        print(f"Полные: {x['филиал']} {x['время']} {x['занятие']} — {x['загрузка_проц']} %", file=sys.stderr)
    for x in r["empty"]:
        print(f"Пустые: {x['филиал']} {x['время']} {x['занятие']} — {x['загрузка_проц']} %", file=sys.stderr)
    if r["no_classes"]:
        print("Нет данных о занятиях: " + ", ".join(r["no_classes"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
