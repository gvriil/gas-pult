"""Госпошлина в суд общей юрисдикции по пп. 1–2 п. 1 ст. 333.19 НК РФ (ред. ФЗ от 08.08.2024 № 259-ФЗ, действует с
08.09.2024; сверено 02.11.2026) — для черновика заявления о выдаче судебного приказа или иска о взыскании долга.

Иск имущественного характера (пп. 1) — по цене иска; заявление о выдаче судебного приказа (пп. 2) — 50 % от пошлины
по пп. 1, но не менее 2 000 руб. Пошлина округляется до полного рубля (п. 6 ст. 52 НК РФ: менее 50 коп. отбрасываются,
50 коп. и более — до рубля). Отменили приказ и подаёте иск — уплаченная пошлина засчитывается (пп. 13 п. 1
ст. 333.20 НК РФ). Только стандартная библиотека.

    python3 duty.py 45000.50        → иск и приказ: суммы пошлины

ЧЕРНОВИК: шкалу сверять с КонсультантПлюс перед подачей — проверяет юрист.
"""

from __future__ import annotations

import sys
from decimal import ROUND_HALF_UP, Decimal

CHECKED = "2026-11-02"
# (до суммы включительно, фиксированная часть, процент сверх, с какой суммы процент) — пп. 1 п. 1 ст. 333.19 НК РФ
SCALE = [
    (Decimal(100_000), Decimal(4_000), Decimal(0), Decimal(0)),
    (Decimal(300_000), Decimal(4_000), Decimal(3), Decimal(100_000)),
    (Decimal(500_000), Decimal(10_000), Decimal("2.5"), Decimal(300_000)),
    (Decimal(1_000_000), Decimal(15_000), Decimal(2), Decimal(500_000)),
    (Decimal(3_000_000), Decimal(25_000), Decimal(1), Decimal(1_000_000)),
    (Decimal(8_000_000), Decimal(45_000), Decimal("0.7"), Decimal(3_000_000)),
    (Decimal(24_000_000), Decimal(80_000), Decimal("0.35"), Decimal(8_000_000)),
    (Decimal(50_000_000), Decimal(136_000), Decimal("0.3"), Decimal(24_000_000)),
    (Decimal(100_000_000), Decimal(214_000), Decimal("0.2"), Decimal(50_000_000)),
]
OVER = (Decimal(314_000), Decimal("0.15"), Decimal(100_000_000), Decimal(900_000))   # свыше 100 млн, не более 900 тыс.
ORDER_MIN = Decimal(2_000)


def rub(x: Decimal) -> Decimal:
    return x.quantize(Decimal(1), ROUND_HALF_UP)


def claim(price: Decimal) -> Decimal:
    """Пошлина по иску имущественного характера, цена иска price руб."""
    price = Decimal(price)
    if price <= 0:
        raise ValueError("цена иска — больше нуля")
    for top, fixed, pct, base in SCALE:
        if price <= top:
            return rub(fixed + (price - base) * pct / 100)
    fixed, pct, base, cap = OVER
    return min(rub(fixed + (price - base) * pct / 100), cap)


def order(price: Decimal) -> Decimal:
    """Пошлина за заявление о выдаче судебного приказа: 50 % от пошлины по иску, не менее 2 000 руб."""
    return max(rub(claim(price) / 2), ORDER_MIN)


def main(argv: list[str]) -> int:
    try:
        price = Decimal(argv[0].replace(" ", "").replace(",", "."))
        print(f"Цена {price} ₽: иск — {claim(price)} ₽, судебный приказ — {order(price)} ₽ "
              f"(ст. 333.19 НК РФ, сверено {CHECKED}; ЧЕРНОВИК — проверяет юрист)")
    except (IndexError, ArithmeticError, ValueError) as e:
        print(f"duty.py <цена иска, руб.> — {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
