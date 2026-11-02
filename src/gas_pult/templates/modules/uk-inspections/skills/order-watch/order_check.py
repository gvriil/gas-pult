"""Пункты предписаний жилинспекции: сколько рабочих дней до срока, когда готовить отчёт, где нет фото и актов.

Пункты — data/orders.csv: предписание, дата, пункт, нарушение, дом, исполнитель, срок, статус (открыт | выполнен |
продление_запрошено | продлено), примечание. Фото и акты — папка evidence/<предписание>/<пункт>/ (README не считается).
Рабочие дни — навык workdays блока «Сроки» (рядом в .claude/skills/workdays/, календарь РФ; data/calendar-ru.csv
клиента важнее). Только стандартная библиотека; ничего не отправляет и в реестр не пишет.

    python3 order_check.py --orders data/orders.csv --evidence evidence --on 2026-11-02 --report-days 5 --warn-days 3
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "workdays"))          # .claude/skills/workdays — навык блока deadlines
import workdays  # noqa: E402

OPEN = {"открыт", "продление_запрошено", "продлено"}
SKIP = {"README.md", ".DS_Store", ".gitkeep"}


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def back(due: date, n: int, cal: dict) -> date:
    """Последний рабочий день, после которого до срока включительно ровно n рабочих дней (left = n)."""
    d, left = due, n
    while left > 0:
        if workdays.is_workday(d, cal):
            left -= 1
        d -= timedelta(days=1)
    while not workdays.is_workday(d, cal):
        d -= timedelta(days=1)
    return d


def evidence(base: Path, order: str, item: str) -> int:
    folder = base / order.replace("/", "-") / item
    return sum(1 for p in folder.rglob("*") if p.is_file() and p.name not in SKIP) if folder.is_dir() else 0


def check(rows: list[dict], on: date, cal: dict, report_days: int = 5, warn_days: int = 3,
          base: Path | None = None) -> list[dict]:
    """Открытые пункты: left — рабочих дней до срока (0 — сегодня, <0 — просрочено), report_from — с какого дня
    готовить отчёт, stage — что делать сегодня, files — сколько фото и актов в папке пункта."""
    out = []
    for r in rows:
        if r.get("статус", "открыт") not in OPEN:
            continue
        due = date.fromisoformat(r["срок"])
        left = workdays.left(due, on, cal)
        report_from = back(due, report_days, cal)
        files = evidence(base, r["предписание"], r["пункт"]) if base else 0
        if left < 0:
            stage = "ПРОСРОЧЕНО"
        elif left == 0:
            stage = "СРОК СЕГОДНЯ"
        elif on >= report_from:
            stage = "готовить отчёт" if files else "не успеваем? нет фото и актов"
        elif left <= report_days + warn_days:
            stage = "напомнить исполнителю"
        else:
            stage = "в работе"
        out.append({"предписание": r["предписание"], "пункт": r["пункт"], "дом": r.get("дом", ""),
                    "исполнитель": r.get("исполнитель", ""), "срок": due.isoformat(), "left": left,
                    "report_from": report_from.isoformat(), "files": files, "stage": stage,
                    "статус": r.get("статус", "открыт")})
    return sorted(out, key=lambda x: (x["left"], x["предписание"], x["пункт"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Сроки пунктов предписаний жилинспекции")
    ap.add_argument("--orders", type=Path, required=True)
    ap.add_argument("--evidence", type=Path, default=Path("evidence"))
    ap.add_argument("--on", type=date.fromisoformat, default=date.today())
    ap.add_argument("--report-days", type=int, default=5)
    ap.add_argument("--warn-days", type=int, default=3)
    a = ap.parse_args(argv)
    try:
        rows = check(read(a.orders), a.on, workdays.load(), a.report_days, a.warn_days, a.evidence)
    except workdays.NoCalendar as e:
        print(e, file=sys.stderr)
        return 2
    except (KeyError, ValueError) as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 1
    w = csv.DictWriter(sys.stdout, fieldnames=["предписание", "пункт", "дом", "исполнитель", "срок", "left",
                                               "report_from", "files", "stage", "статус"])
    w.writeheader()
    w.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
