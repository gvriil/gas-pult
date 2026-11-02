"""Рассрочки клубных карт: какие платежи скоро, сегодня и просрочены (по корзинам блока «Дебиторка»). Только
стандартная библиотека; ничего не отправляет и никого не блокирует.

Графики: data/installments.csv — договор, клиент_id, имя, платёж (номер), срок, сумма, оплачено, дата_оплаты.

    python3 installments.py --today 2026-11-02 [--file data/installments.csv] [--remind-days 3]
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

BUCKETS = ((30, "1–30"), (60, "31–60"), (90, "61–90"))


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def money(s: str) -> Decimal:
    return Decimal((s or "0").replace(" ", "").replace(",", "."))


def bucket(days: int) -> str:
    return next((name for lim, name in BUCKETS if days <= lim), "больше 90")


def status(row: dict, today: date, remind_days: int = 3) -> dict:
    """→ {"вид": оплачен | не_наступил | скоро | сегодня | просрочен, "дней", "долг", "корзина"}."""
    debt = money(row["сумма"]) - money(row.get("оплачено", ""))
    days = (today - date.fromisoformat(row["срок"])).days
    if debt <= 0:
        kind = "оплачен"
    elif days > 0:
        kind = "просрочен"
    elif days == 0:
        kind = "сегодня"
    elif -days <= remind_days:
        kind = "скоро"
    else:
        kind = "не_наступил"
    return {"вид": kind, "дней": days, "долг": f"{max(debt, Decimal('0')):.2f}",
            "корзина": bucket(days) if kind == "просрочен" else ""}


def report(rows: list[dict], today: date, remind_days: int = 3) -> dict:
    out: dict = {"скоро": [], "сегодня": [], "просрочен": [], "итого_просрочено": "0.00"}
    total = Decimal("0")
    for r in rows:
        s = status(r, today, remind_days)
        if s["вид"] in out:
            out[s["вид"]].append(r | s)
            if s["вид"] == "просрочен":
                total += money(s["долг"])
    out["просрочен"].sort(key=lambda x: -x["дней"])
    out["итого_просрочено"] = f"{total:.2f}"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Рассрочки: скоро, сегодня, просрочено")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--file", type=Path, default=Path("data/installments.csv"))
    ap.add_argument("--remind-days", type=int, default=3)
    a = ap.parse_args(argv)
    r = report(read(a.file), date.fromisoformat(a.today), a.remind_days)
    w = csv.writer(sys.stdout)
    w.writerow(["вид", "договор", "имя", "платёж", "срок", "долг", "дней", "корзина"])
    for kind in ("скоро", "сегодня", "просрочен"):
        for x in r[kind]:
            w.writerow([kind, x["договор"], x["имя"], x["платёж"], x["срок"], x["долг"], x["дней"], x["корзина"]])
    print(f"Просрочено всего: {r['итого_просрочено']} ₽", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
