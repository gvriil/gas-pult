"""Сверка моек корпоративных автопарков с договорами за месяц: сколько моек, в лимите ли, сумма к счёту.

Договор: data/fleet_contracts.csv — договор, контрагент, госномера (через «;»), лимит_моек_мес (на договор), цена,
цена_сверх, отсрочка_дн, стоп. Мойки: data/fleet_washes.csv — дата, госномер, филиал, услуга.
Сверх лимита — не выставляем сами: отдельная строка «вопрос человеку». Госномер не из договора — «чужой номер».
Мойка при действующем стопе — «мойка при стопе». Только стандартная библиотека; ничего не отправляет.

    python3 fleet_check.py --contracts data/fleet_contracts.csv --washes data/fleet_washes.csv --month 2026-10 \\
        [--out outbox/fleet-2026-10.csv]
"""

from __future__ import annotations

import argparse
import csv
import sys
from decimal import Decimal
from pathlib import Path

LAT = str.maketrans("ABEKMHOPCTYX", "АВЕКМНОРСТУХ")          # латиница, похожая на кириллицу в госномерах


def plate(s: str) -> str:
    """Госномер для сравнения: без пробелов, верхний регистр, латинские двойники → кириллица."""
    return "".join(s.split()).upper().translate(LAT)


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def money(s: str) -> Decimal:
    return Decimal((s or "0").replace(" ", "").replace(",", "."))


def reconcile(contracts: list[dict], washes: list[dict], month: str) -> dict:
    """→ {"contracts": [итог по договору], "unknown": [мойки с чужим номером]}. month — «ГГГГ-ММ»."""
    by_plate: dict[str, dict] = {}
    for c in contracts:
        for p in c["госномера"].split(";"):
            if p.strip():
                by_plate[plate(p)] = c
    count = {c["договор"]: [] for c in contracts}
    unknown = []
    for w in sorted(washes, key=lambda w: (w["дата"], w.get("время", ""))):
        if not w["дата"].startswith(month):
            continue
        c = by_plate.get(plate(w["госномер"]))
        if c is None:
            unknown.append(w)
        else:
            count[c["договор"]].append(w)
    out = []
    for c in contracts:
        ws = count[c["договор"]]
        limit = int(c.get("лимит_моек_мес") or 0)
        inside = len(ws) if not limit else min(len(ws), limit)
        over = len(ws) - inside
        price, over_price = money(c["цена"]), money(c.get("цена_сверх") or c["цена"])
        stopped = c.get("стоп", "").lower() == "да"
        out.append({
            "договор": c["договор"], "контрагент": c["контрагент"], "моек": len(ws), "лимит": limit or "без лимита",
            "в_лимите": inside, "сверх": over, "к_счёту": str(inside * price),
            "сверх_сумма_вопрос": str(over * over_price), "при_стопе": len(ws) if stopped else 0,
            "по_филиалам": "; ".join(f"{b}: {n}" for b, n in sorted(_branches(ws).items())),
        })
    return {"contracts": out, "unknown": unknown}


def _branches(ws: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for w in ws:
        out[w["филиал"]] = out.get(w["филиал"], 0) + 1
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Сверить мойки автопарков с договорами за месяц")
    ap.add_argument("--contracts", type=Path, required=True)
    ap.add_argument("--washes", type=Path, required=True)
    ap.add_argument("--month", required=True, help="ГГГГ-ММ")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    r = reconcile(read(a.contracts), read(a.washes), a.month)
    out = open(a.out, "w", encoding="utf-8", newline="") if a.out else sys.stdout  # noqa: SIM115
    w = csv.DictWriter(out, fieldnames=list(r["contracts"][0]) if r["contracts"] else ["договор"])
    w.writeheader()
    w.writerows(r["contracts"])
    if a.out:
        out.close()
    for x in r["unknown"]:
        print(f"Чужой номер: {x['дата']} {x['филиал']} {x['госномер']} — нет в договорах, вопрос человеку",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
