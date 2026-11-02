"""Пени за жилое помещение и коммунальные услуги по ч. 14 ст. 155 ЖК РФ — расчёт для черновика, не для суда без юриста.

Правило: с 31-го по 90-й день после срока оплаты — 1/300 ставки, с 91-го дня — 1/130 ставки от не выплаченной
в срок суммы за каждый день просрочки, по день фактической оплаты включительно. Ставка — ставка рефинансирования
(с 01.01.2016 равна ключевой) ЦБ РФ, действующая на день фактической оплаты; не оплачено — на дату расчёта.
Ограничения из data/penalty_rules.csv: «мораторий» — дни, за которые пени не начисляются; «ставка_не_выше» — в эти
дни ставка не выше значения (ПП РФ № 474 и продления, сейчас — ПП РФ от 18.03.2025 № 329: минимум из ставки на
27.02.2022 и на день оплаты); «долг_до» — правило только для долга со сроком оплаты раньше этой даты (мораторий
ПП РФ № 497 — только на долг, возникший до 01.04.2022). Ставки ЦБ — data/key_rate.csv, человек дописывает новые.
Оплата без периода гасит самый старый долг (ст. 319.1 ГК РФ). Только стандартная библиотека; ничего не отправляет.

    python3 penalty.py --charges data/charges.csv --payments data/payments.csv --rates data/key_rate.csv \\
        --rules data/penalty_rules.csv --on 2026-11-02 [--ls 000000000001] [--out outbox/peni.csv]

РАСЧЁТ — ЧЕРНОВИК: сверять в КонсультантПлюс (калькулятор пеней) и у юриста перед претензией и заявлением.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

KOP = Decimal("0.01")
NOTE = "ЧЕРНОВИК расчёта пеней (ч. 14 ст. 155 ЖК РФ) — сверять в КонсультантПлюс, проверяет юрист"


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def money(s: str) -> Decimal:
    return Decimal((s or "0").replace(" ", "").replace(",", "."))


def rates_from(rows: list[dict]) -> list[tuple[date, Decimal]]:
    """data/key_rate.csv: с,ставка — дата начала действия и ставка в процентах годовых."""
    return sorted((date.fromisoformat(r["с"]), money(r["ставка"])) for r in rows)


def rules_from(rows: list[dict]) -> list[tuple]:
    """data/penalty_rules.csv: с,по,правило,значение,долг_до — по включительно; правило: мораторий | ставка_не_выше;
    долг_до (необязательно) — правило только для долга со сроком оплаты раньше этой даты."""
    out = []
    for r in rows:
        kind = r["правило"]
        if kind not in {"мораторий", "ставка_не_выше"}:
            raise ValueError(f"неизвестное правило «{kind}» — только «мораторий» или «ставка_не_выше»")
        before = date.fromisoformat(r["долг_до"]) if r.get("долг_до") else None
        start, stop = date.fromisoformat(r["с"]), date.fromisoformat(r["по"])
        out.append((start, stop, kind, money(r.get("значение", "")), before))
    return out


def rate_on(d: date, rates: list[tuple[date, Decimal]]) -> Decimal:
    found = [r for start, r in rates if start <= d]
    if not found:
        raise LookupError(f"нет ставки ЦБ на {d} — допишите data/key_rate.csv")
    return found[-1]


def share(k: int) -> Decimal:
    """Доля ставки на k-й день после срока оплаты: до 30-го — 0, 31–90 — 1/300, с 91-го — 1/130."""
    return Decimal(0) if k <= 30 else Decimal(1) / 300 if k <= 90 else Decimal(1) / 130


def accrue(amount: Decimal, due: date, end: date, rate: Decimal, rules) -> Decimal:
    """Пени на сумму amount, не оплаченную в срок due, по день end включительно при ставке rate (%)."""
    total, day = Decimal(0), due + timedelta(days=31)
    while day <= end:
        r = rate
        for start, stop, kind, value, *before in rules:
            if start <= day <= stop and not (before and before[0] and due >= before[0]):
                r = Decimal(0) if kind == "мораторий" else min(r, value)
        total += amount * r / 100 * share((day - due).days)
        day += timedelta(days=1)
    return total.quantize(KOP, ROUND_HALF_UP)


PAY_15 = "2026-02"      # ФЗ от 24.06.2025 № 177-ФЗ (с 01.03.2026): до 15-го — с платы за февраль 2026 (по обзорам)


def default_due(period: str, pay_day: int = 0) -> date:
    """Срок оплаты за месяц «ГГГГ-ММ» — число следующего месяца по ч. 1 ст. 155 ЖК РФ: до 10-го (до 177-ФЗ, договор
    мог установить иной срок), с платы за февраль 2026 — до 15-го (единый срок). pay_day — своё число, если задано."""
    day = pay_day or (15 if period >= PAY_15 else 10)
    y, m = map(int, period.split("-"))
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return date(y, m, day)


def allocate(charges: list[dict], payments: list[dict]) -> dict[str, list[tuple[date, Decimal]]]:
    """Оплаты по периодам: с периодом — в этот период (излишек — в самый старый долг), без — в самый старый."""
    left = {c["период"]: money(c["начислено"]) for c in charges}
    out: dict[str, list[tuple[date, Decimal]]] = {p: [] for p in left}
    for p in sorted(payments, key=lambda x: x["дата"]):
        d, amt = date.fromisoformat(p["дата"]), money(p["сумма"])
        order = ([p["период"]] if p.get("период") in left else []) + sorted(left)
        for per in order:
            if amt <= 0:
                break
            use = min(amt, left[per])
            if use > 0:
                out[per].append((d, use))
                left[per] -= use
                amt -= use
    return out


def account(charges: list[dict], payments: list[dict], on: date, rates, rules, pay_day: int = 0) -> list[dict]:
    """Расчёт по одному лицевому счёту: строка на период — начислено, оплачено, остаток, дней просрочки, пени."""
    paid = allocate(charges, payments)
    rows = []
    for c in sorted(charges, key=lambda x: x["период"]):
        due = date.fromisoformat(c["срок_оплаты"]) if c.get("срок_оплаты") else default_due(c["период"], pay_day)
        balance, peni = money(c["начислено"]), Decimal(0)
        for d, amt in paid[c["период"]]:
            balance -= amt
            if d > due:                                  # оплачено после срока — пени на эту часть до дня оплаты
                peni += accrue(amt, due, d, rate_on(d, rates), rules)
        if balance > 0 and on > due:
            peni += accrue(balance, due, on, rate_on(on, rates), rules)
        rows.append({"период": c["период"], "срок_оплаты": due.isoformat(), "начислено": str(money(c["начислено"])),
                     "оплачено": str(money(c["начислено"]) - balance), "остаток": str(balance),
                     "дней_просрочки": max((on - due).days, 0) if balance > 0 else 0, "пени": str(peni.quantize(KOP))})
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Пени за ЖКУ по ч. 14 ст. 155 ЖК РФ (черновик расчёта)")
    ap.add_argument("--charges", type=Path, required=True)
    ap.add_argument("--payments", type=Path, required=True)
    ap.add_argument("--rates", type=Path, required=True)
    ap.add_argument("--rules", type=Path)
    ap.add_argument("--on", type=date.fromisoformat, default=date.today())
    ap.add_argument("--ls", help="только этот лицевой счёт")
    ap.add_argument("--pay-day", type=int, default=0, help="своё число срока оплаты (по умолчанию — по ЖК РФ)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    try:
        rates = rates_from(read(a.rates))
        rules = rules_from(read(a.rules)) if a.rules else []
        charges, payments = read(a.charges), read(a.payments)
        out = []
        for ls in sorted({c["лс"] for c in charges}):
            if a.ls and ls != a.ls:
                continue
            for r in account([c for c in charges if c["лс"] == ls], [p for p in payments if p["лс"] == ls],
                             a.on, rates, rules, a.pay_day):
                out.append({"лс": ls} | r)
    except (LookupError, ValueError, KeyError) as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 2
    fields = ["лс", "период", "срок_оплаты", "начислено", "оплачено", "остаток", "дней_просрочки", "пени"]
    f = a.out.open("w", encoding="utf-8", newline="") if a.out else sys.stdout
    print(f"# {NOTE}; расчёт на {a.on}", file=f)
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(out)
    total = {ls: sum(Decimal(r["пени"]) for r in out if r["лс"] == ls) for ls in {r["лс"] for r in out}}
    for ls, s in sorted(total.items()):
        debt = sum(Decimal(r["остаток"]) for r in out if r["лс"] == ls)
        print(f"{ls}: долг {debt} ₽, пени {s} ₽", file=sys.stderr)
    if a.out:
        f.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
