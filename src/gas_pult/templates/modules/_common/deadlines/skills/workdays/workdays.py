"""Рабочие дни РФ по производственному календарю: срок «N рабочих дней», сколько осталось, рабочий ли день.

Календарь — calendar-ru.csv рядом со скриптом; файл клиента data/calendar-ru.csv (в папке, откуда запускают) важнее.
Формат: дата,вид,основание — вид «выходной» (нерабочий будний день) или «рабочий» (рабочая суббота/воскресенье).
Года нет в календаре — код выхода 2: не угадываем, календарь обновляют ежегодно. Только стандартная библиотека.
"""

from __future__ import annotations

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent


class NoCalendar(LookupError):
    pass


def load(paths: list[Path] | None = None) -> dict[date, bool]:
    """Особые дни: дата → рабочий ли. Файлы — по порядку, следующий перекрывает предыдущий."""
    out: dict[date, bool] = {}
    for p in paths if paths is not None else [HERE / "calendar-ru.csv", Path.cwd() / "data" / "calendar-ru.csv"]:
        if not p.is_file():
            continue
        with p.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                out[date.fromisoformat(row["дата"].strip())] = row["вид"].strip() == "рабочий"
    return out


def years(cal: dict[date, bool]) -> set[int]:
    return {d.year for d in cal}


def is_workday(d: date, cal: dict[date, bool]) -> bool:
    if d.year not in years(cal):
        raise NoCalendar(f"нет производственного календаря на {d.year} — обновите calendar-ru.csv")
    return cal.get(d, d.isoweekday() < 6)


def add(start: date, n: int, cal: dict[date, bool]) -> date:
    """N-й рабочий день после start (сам день start не считается — ст. 191 ГК РФ)."""
    d, left = start, n
    while left > 0:
        d += timedelta(days=1)
        if is_workday(d, cal):
            left -= 1
    return d


def next_workday(d: date, cal: dict[date, bool]) -> date:
    while not is_workday(d, cal):
        d += timedelta(days=1)
    return d


def left(due: date, today: date, cal: dict[date, bool]) -> int:
    """Рабочих дней после сегодняшнего до срока включительно: 0 — срок сегодня, 1 — завтра (рабочий);
    отрицательное — просрочено на столько рабочих дней (не меньше 1 по модулю)."""
    lo, hi = sorted((today, due))
    n = sum(is_workday(lo + timedelta(days=i), cal) for i in range(1, (hi - lo).days + 1))
    return n if due >= today else -max(n, 1)


def main(argv: list[str]) -> int:
    cal = load()
    try:
        cmd, *args = argv or ["help"]
        if cmd == "add":
            print(add(date.fromisoformat(args[0]), int(args[1]), cal))
        elif cmd == "left":
            today = date.fromisoformat(args[1]) if len(args) > 1 else date.today()
            print(left(date.fromisoformat(args[0]), today, cal))
        elif cmd == "is":
            print("да" if is_workday(date.fromisoformat(args[0]), cal) else "нет")
        elif cmd == "next":
            print(next_workday(date.fromisoformat(args[0]), cal))
        elif cmd == "years":
            print(" ".join(map(str, sorted(years(cal)))))
        else:
            print("workdays.py add <дата> <N> | left <срок> [<сегодня>] | is <дата> | next <дата> | years")
            return 1
    except NoCalendar as e:
        print(e, file=sys.stderr)
        return 2
    except (IndexError, ValueError) as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
