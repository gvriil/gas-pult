"""Детское направление: кто по возрасту выходит из своей группы — сейчас или в ближайшие N дней — и в какую группу
того же направления его можно перевести. Решает человек; скрипт только считает. Только стандартная библиотека.

Дети: data/children.csv — id, имя, дата_рождения, родитель_id, группа, согласие_родителя. Группы: data/groups.csv —
группа, направление, возраст_от, возраст_до (полных лет, включительно), филиал.
Возраст — полных лет; родившиеся 29 февраля в невисокосный год становятся старше 1 марта.

    python3 age_transition.py --today 2026-11-02 [--children data/children.csv] [--groups data/groups.csv] \\
        [--horizon 60]
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

YES = {"да", "yes", "1", "true"}


def yes(v: str | None) -> bool:
    return (v or "").strip().lower() in YES


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def age(born: date, on: date) -> int:
    """Полных лет на дату on."""
    return on.year - born.year - ((on.month, on.day) < (born.month, born.day))


def birthday(born: date, years: int) -> date:
    """Дата, когда исполнится years лет (29 февраля в невисокосный год — 1 марта)."""
    try:
        return born.replace(year=born.year + years)
    except ValueError:
        return date(born.year + years, 3, 1)


def transitions(children: list[dict], groups: list[dict], today: date, horizon: int = 60) -> dict:
    """→ {"move": [...], "skipped": [...]}. move: ребёнок, его группа, когда выходит по возрасту, варианты групп."""
    by = {g["группа"]: g for g in groups}
    out: dict = {"move": [], "skipped": []}
    until = today + timedelta(days=horizon)
    for c in children:
        if not yes(c.get("согласие_родителя")):
            out["skipped"].append({"id": c["id"], "почему": "нет согласия родителя на обработку данных ребёнка"})
            continue
        g = by.get(c.get("группа", ""))
        if not g or not c.get("дата_рождения"):
            out["skipped"].append({"id": c["id"], "почему": "нет группы или даты рождения"})
            continue
        born = date.fromisoformat(c["дата_рождения"])
        lo, hi = int(g["возраст_от"]), int(g["возраст_до"])
        now = age(born, today)
        if now < lo:
            when, why, new_age = today, f"младше группы: {now} лет, группа {lo}–{hi}", now
        elif age(born, until) > hi:
            when = birthday(born, hi + 1)
            when = max(when, today)
            why, new_age = f"исполнится {hi + 1} лет", hi + 1
        else:
            continue
        options = [x["группа"] for x in groups if x["направление"] == g["направление"] and x["группа"] != g["группа"]
                   and int(x["возраст_от"]) <= new_age <= int(x["возраст_до"])]
        own = [o for o in options if by[o].get("филиал") == g.get("филиал")]
        out["move"].append({"id": c["id"], "имя": c["имя"], "родитель_id": c.get("родитель_id", ""),
                            "группа": g["группа"], "возраст": now, "с": when.isoformat(), "почему": why,
                            "варианты": own + [o for o in options if o not in own]})
    out["move"].sort(key=lambda x: x["с"])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Детские группы: переход по возрасту")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--children", type=Path, default=Path("data/children.csv"))
    ap.add_argument("--groups", type=Path, default=Path("data/groups.csv"))
    ap.add_argument("--horizon", type=int, default=60)
    a = ap.parse_args(argv)
    r = transitions(read(a.children), read(a.groups), date.fromisoformat(a.today), a.horizon)
    w = csv.writer(sys.stdout)
    w.writerow(["id", "имя", "родитель_id", "группа", "возраст", "с", "почему", "варианты"])
    for x in r["move"]:
        w.writerow([x["id"], x["имя"], x["родитель_id"], x["группа"], x["возраст"], x["с"], x["почему"],
                    "; ".join(x["варианты"]) or "нет подходящей группы — вопрос человеку"])
    for x in r["skipped"]:
        print(f"Пропущено {x['id']}: {x['почему']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
