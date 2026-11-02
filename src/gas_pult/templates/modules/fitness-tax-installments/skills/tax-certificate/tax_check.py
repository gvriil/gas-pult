"""Заявки на справку для социального вычета за физкультурно-оздоровительные услуги (пп. 7 п. 1 ст. 219 НК РФ):
проверка заявки до черновика справки. Только стандартная библиотека; ничего не выдаёт и не отправляет.

Проверяет: ИНН плательщика (12 цифр, контрольные числа), год (вычет — с расходов 2022 года), клуб в перечне
организаций за этот год (годы ставит человек в [settings]), за кого: сам; ребёнок или подопечный — до 18 лет или до
24 при очном обучении на дату оплаты; родитель — расходы с 2026 года и родитель получает пенсию. Сумма — оплаты
плательщика за год по услугам из перечня видов услуг (распоряжение Правительства РФ № 2466-р). Правила — сверены
02.11.2026, сверять ежегодно (CLAUDE.md модуля).

Заявки: data/tax_requests.csv — id, получено, клиент_id, плательщик, инн, год, за_кого (сам | ребёнок |
подопечный | родитель), фио_за_кого, дата_рождения_за_кого, очно, пенсионер, статус. Оплаты: data/payments.csv —
дата, клиент_id (кто платил), сумма, услуга, по_перечню (да/нет).

    python3 tax_check.py --in-list 2025,2026 [--requests data/tax_requests.csv] [--payments data/payments.csv]
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

YES = {"да", "yes", "1", "true"}
FIRST_YEAR = 2022               # пп. 7 п. 1 ст. 219 НК РФ — расходы с 01.01.2022
PARENTS_FROM = 2026             # за родителей-пенсионеров — расходы с 01.01.2026 (425-ФЗ от 28.11.2025)
W11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
W12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def yes(v: str | None) -> bool:
    return (v or "").strip().lower() in YES


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def money(s: str) -> Decimal:
    return Decimal((s or "0").replace(" ", "").replace(",", "."))


def inn_ok(inn: str) -> bool:
    """ИНН физического лица: 12 цифр, два контрольных числа."""
    s = (inn or "").replace(" ", "")
    if len(s) != 12 or not s.isdigit():
        return False
    d = [int(c) for c in s]
    c11 = sum(w * x for w, x in zip(W11, d[:10], strict=True)) % 11 % 10
    c12 = sum(w * x for w, x in zip(W12, d[:11], strict=True)) % 11 % 10
    return d[10] == c11 and d[11] == c12


def age(born: date, on: date) -> int:
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def years(s: str) -> set[int]:
    return {int(x) for x in str(s).replace(";", ",").split(",") if x.strip().isdigit()}


def check(req: dict, payments: list[dict], in_list: set[int]) -> dict:
    """→ {"id", "ok", "problems", "сумма", "не_по_перечню"}. ok — можно готовить черновик справки."""
    problems = []
    if not inn_ok(req.get("инн", "")):
        problems.append("ИНН: не 12 цифр или не сходятся контрольные числа — уточнить у плательщика")
    year = int(req.get("год") or 0)
    if year < FIRST_YEAR:
        problems.append(f"год {year}: вычет за физкультурно-оздоровительные услуги — с расходов {FIRST_YEAR} года")
    if year not in in_list:
        problems.append(f"клуба нет в перечне организаций за {year} год (отметка человека в [settings]) — справку "
                        "не выдаём, вопрос человеку")
    mine = [p for p in payments if p.get("клиент_id") == req.get("клиент_id") and p.get("дата", "")[:4] == str(year)]
    ok_pay = [p for p in mine if yes(p.get("по_перечню"))]
    total = sum((money(p["сумма"]) for p in ok_pay), Decimal("0"))
    other = sum((money(p["сумма"]) for p in mine if not yes(p.get("по_перечню"))), Decimal("0"))
    if not ok_pay:
        problems.append(f"нет оплат этого плательщика за {year} год по услугам из перечня")
    who = req.get("за_кого", "сам")
    if who in ("ребёнок", "подопечный"):
        born = req.get("дата_рождения_за_кого")
        if not born or not req.get("фио_за_кого"):
            problems.append("нет ФИО или даты рождения ребёнка — уточнить у родителя")
        else:
            b = date.fromisoformat(born)
            dates = [date.fromisoformat(p["дата"]) for p in ok_pay] or [date(year, 12, 31)]
            for d in dates:
                a = age(b, d)
                if a >= 24 or (a >= 18 and not yes(req.get("очно"))):
                    problems.append(f"на {d.isoformat()} ребёнку {a} лет: вычет — до 18 лет или до 24 при очном "
                                    "обучении (нужна справка об очном обучении)")
                    break
    elif who == "родитель":
        if year < PARENTS_FROM:
            problems.append(f"за родителей — только расходы с {PARENTS_FROM} года")
        if not yes(req.get("пенсионер")):
            problems.append("за родителя — только если он получает пенсию")
        if not req.get("фио_за_кого"):
            problems.append("нет ФИО родителя")
    elif who != "сам":
        problems.append(f"за_кого = «{who}»: вычет — за себя, ребёнка, подопечного или родителя (с 2026)")
    return {"id": req["id"], "ok": not problems, "problems": problems, "сумма": f"{total:.2f}",
            "не_по_перечню": f"{other:.2f}"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Заявки на справку для вычета за фитнес: проверка")
    ap.add_argument("--requests", type=Path, default=Path("data/tax_requests.csv"))
    ap.add_argument("--payments", type=Path, default=Path("data/payments.csv"))
    ap.add_argument("--in-list", default="", help="годы, за которые клуб в перечне, через запятую")
    a = ap.parse_args(argv)
    pays = read(a.payments)
    w = csv.writer(sys.stdout)
    w.writerow(["id", "можно", "сумма", "не_по_перечню", "что_не_так"])
    for r in read(a.requests):
        if r.get("статус") in ("выдана", "отказ"):
            continue
        c = check(r, pays, years(a.in_list))
        w.writerow([c["id"], "да" if c["ok"] else "нет", c["сумма"], c["не_по_перечню"], "; ".join(c["problems"])])
    return 0


if __name__ == "__main__":
    sys.exit(main())
