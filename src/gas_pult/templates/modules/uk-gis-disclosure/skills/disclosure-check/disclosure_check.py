"""Сверка раскрытия информации управляющей организацией в ГИС ЖКХ: что не размещено или размещено с опозданием.

Чек-лист — data/disclosure_checklist.csv: код, что, уровень (дом | организация), периодичность (ежемесячно |
ежеквартально | ежегодно | при_изменении), смещение_мес и срок_день (срок периодического: срок_день-е число через
смещение_мес месяцев после конца периода; срок_день больше дней в месяце — последний день), дней (при_изменении:
срок — через столько календарных дней после изменения), основание.
Выгрузка — data/gis_export.csv, которую делает человек из ГИС ЖКХ (или ведёт вручную): код, дом, период (ГГГГ-ММ,
ГГГГ-КN, ГГГГ или дата изменения ГГГГ-ММ-ДД для при_изменении), размещено (дата или пусто).
Дома — data/houses.csv (дом, управляем_с — с какой даты дом в управлении: раньше сроки не считаем). Только стандартная библиотека; в ГИС ЖКХ не ходит, ничего не отправляет.

    python3 disclosure_check.py --checklist data/disclosure_checklist.csv --export data/gis_export.csv \\
        --houses data/houses.csv --on 2026-11-02 [--months 3] [--soon 10]
"""

from __future__ import annotations

import argparse
import calendar
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

FIELDS = ["состояние", "код", "что", "дом", "период", "срок", "размещено", "основание"]


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def month_add(y: int, m: int, k: int) -> tuple[int, int]:
    n = y * 12 + (m - 1) + k
    return n // 12, n % 12 + 1


def day_in(y: int, m: int, d: int) -> date:
    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


def periods(kind: str, on: date, months: int) -> list[tuple[str, int, int]]:
    """Периоды, закончившиеся за months + 24 месяца до on: (имя, год, месяц конца периода)."""
    out = []
    for back in range(months + 24, 0, -1):
        y, m = month_add(on.year, on.month, -back)
        if kind == "ежемесячно":
            out.append((f"{y}-{m:02d}", y, m))
        elif kind == "ежеквартально" and m % 3 == 0:
            out.append((f"{y}-К{m // 3}", y, m))
        elif kind == "ежегодно" and m == 12:
            out.append((str(y), y, m))
    return out


def due_of(item: dict, y: int, m: int) -> date:
    """Срок периодического пункта: срок_день-е число через смещение_мес месяцев после месяца конца периода."""
    yy, mm = month_add(y, m, int(item.get("смещение_мес") or 1))
    return day_in(yy, mm, int(item["срок_день"]))


def check(checklist: list[dict], export: list[dict], houses: list[dict], on: date, months: int = 3,
          soon: int = 10) -> list[dict]:
    """Только проблемы и ближайшие сроки: «не размещено» (срок прошёл), «размещено с опозданием» (за последний
    месяц), «срок скоро» (в ближайшие soon дней). Размещённое в срок — не выводим."""
    posted: dict[tuple[str, str, str], str] = {}
    for r in export:
        posted[(r["код"], r.get("дом") or "—", r["период"])] = r.get("размещено", "")
    window = on - timedelta(days=31)
    start = {h["дом"]: date.fromisoformat(h["управляем_с"]) for h in houses if h.get("управляем_с")}
    out = []
    for item in checklist:
        targets = ["—"] if item.get("уровень") == "организация" else [h["дом"] for h in houses]
        kind = item["периодичность"]
        for house in targets:
            cases: list[tuple[str, date]] = []
            if kind == "при_изменении":
                for (code, h, per), _ in posted.items():
                    if code == item["код"] and h == house:
                        cases.append((per, date.fromisoformat(per) + timedelta(days=int(item.get("дней") or 0))))
            else:
                every = [(name, due_of(item, y, m)) for name, y, m in periods(kind, on, months)]
                last = max((d for _, d in every if d < on), default=None)      # последний прошедший срок — всегда
                cases = [(n, d) for n, d in every if d >= on - timedelta(days=months * 31) or d == last]
                since = start.get(house)
                cases = [(n, d) for n, d in cases if not since or d >= since]
            for per, due in cases:
                when = posted.get((item["код"], house, per), None)
                if when:
                    if date.fromisoformat(when) > due and date.fromisoformat(when) >= window:
                        state = "размещено с опозданием"
                    else:
                        continue
                elif due < on:
                    state = "не размещено"
                elif (due - on).days <= soon:
                    state = "срок скоро"
                else:
                    continue
                out.append({"состояние": state, "код": item["код"], "что": item["что"], "дом": house, "период": per,
                            "срок": due.isoformat(), "размещено": when or "", "основание": item.get("основание", "")})
    rank = {"не размещено": 0, "размещено с опозданием": 1, "срок скоро": 2}
    return sorted(out, key=lambda r: (rank[r["состояние"]], r["срок"], r["код"], r["дом"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Сверка раскрытия информации УК в ГИС ЖКХ по выгрузке")
    ap.add_argument("--checklist", type=Path, required=True)
    ap.add_argument("--export", type=Path, required=True)
    ap.add_argument("--houses", type=Path, required=True)
    ap.add_argument("--on", type=date.fromisoformat, default=date.today())
    ap.add_argument("--months", type=int, default=3, help="за сколько месяцев смотреть сроки (плюс последний)")
    ap.add_argument("--soon", type=int, default=10, help="«срок скоро» — за столько дней")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    try:
        rows = check(read(a.checklist), read(a.export), read(a.houses), a.on, a.months, a.soon)
    except (KeyError, ValueError) as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 1
    f = a.out.open("w", encoding="utf-8", newline="") if a.out else sys.stdout
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(rows)
    if a.out:
        f.close()
    n = {s: sum(r["состояние"] == s for r in rows) for s in ("не размещено", "размещено с опозданием", "срок скоро")}
    print(f"на {a.on}: " + ", ".join(f"{k} — {v}" for k, v in n.items()), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
