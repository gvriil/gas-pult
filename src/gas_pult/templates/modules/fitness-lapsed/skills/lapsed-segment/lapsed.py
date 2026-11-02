"""«Пропал»: у кого действующая карта, а посещений нет 2–3 недели, — мягкое сообщение; дольше — звонок менеджера.
Для каждого — сколько дней заморозки осталось по правилам клуба (по типу карты). Только стандартная библиотека;
ничего не отправляет и не записывает.

Участники: data/members.csv — id, имя, телефон, канал, тип_карты, филиал, карта_по, заморозка_использовано (дней
в текущем году карты), согласие_уведомления, согласие_реклама, отписка, последнее_сообщение. Посещения:
data/visits.csv — дата, клиент_id, филиал, занятие. Правила заморозки — строка «12 мес.:30;6 мес.:14»: тип карты
(по вхождению в название) → дней в год.

    python3 lapsed.py --today 2026-11-02 [--members data/members.csv] [--visits data/visits.csv] \\
        [--from 14] [--to 21] [--min-gap 14] [--freeze "12 мес.:30;6 мес.:14;3 мес.:7"]
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

YES = {"да", "yes", "1", "true"}


def yes(v: str | None) -> bool:
    return (v or "").strip().lower() in YES


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def parse_freeze(s: str) -> dict[str, int]:
    """«12 мес.:30;6 мес.:14» → {"12 мес.": 30, "6 мес.": 14}."""
    out = {}
    for part in str(s).split(";"):
        if ":" in part:
            k, _, v = part.rpartition(":")
            out[k.strip()] = int(v)
    return out


def freeze_left(m: dict, rules: dict[str, int]) -> int:
    """Сколько дней заморозки осталось: правило по типу карты минус использованное; правила нет — 0."""
    allowed = next((d for k, d in rules.items() if k and k in (m.get("тип_карты") or "")), 0)
    return max(0, allowed - int(m.get("заморозка_использовано") or 0))


def last_visit(visits: list[dict], cid: str, today: date) -> date | None:
    days = [date.fromisoformat(v["дата"]) for v in visits if v["клиент_id"] == cid and v.get("дата")]
    days = [d for d in days if d <= today]
    return max(days) if days else None


def segment(members: list[dict], visits: list[dict], today: date, lapse_from: int = 14, lapse_to: int = 21,
            min_gap: int = 14, rules: dict[str, int] | None = None) -> dict:
    """→ {"soft": мягкое сообщение, "call": звонок менеджера, "skipped": {причина: сколько}}."""
    rules = rules or {}
    out: dict = {"soft": [], "call": [], "skipped": {}}

    def skip(why: str):
        out["skipped"][why] = out["skipped"].get(why, 0) + 1

    for m in members:
        if date.fromisoformat(m["карта_по"]) < today:
            continue                                     # карта кончилась — это модуль продлений
        last = last_visit(visits, m["id"], today)
        days = (today - last).days if last else None
        if days is not None and days < lapse_from:
            continue
        row = {"id": m["id"], "имя": m["имя"], "филиал": m.get("филиал", ""), "дней": days if days is not None else "",
               "последний": last.isoformat() if last else "", "заморозка_дней": freeze_left(m, rules)}
        if days is None or days > lapse_to:
            out["call"].append(row)                      # дольше 3 недель или ни разу — звонит человек
            continue
        if yes(m.get("отписка")) or not yes(m.get("согласие_уведомления")):
            skip("нет согласия на уведомления или отписка")
            continue
        sent = m.get("последнее_сообщение")
        if sent and (today - date.fromisoformat(sent)).days < min_gap:
            skip(f"писали меньше {min_gap} дней назад")
            continue
        out["soft"].append(row)
    out["call"].sort(key=lambda r: -(r["дней"] if r["дней"] != "" else 10 ** 6))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="«Пропал»: 2–3 недели без посещений")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--members", type=Path, default=Path("data/members.csv"))
    ap.add_argument("--visits", type=Path, default=Path("data/visits.csv"))
    ap.add_argument("--from", dest="lapse_from", type=int, default=14)
    ap.add_argument("--to", dest="lapse_to", type=int, default=21)
    ap.add_argument("--min-gap", type=int, default=14)
    ap.add_argument("--freeze", default="")
    a = ap.parse_args(argv)
    r = segment(read(a.members), read(a.visits), date.fromisoformat(a.today), a.lapse_from, a.lapse_to, a.min_gap,
                parse_freeze(a.freeze))
    w = csv.writer(sys.stdout)
    w.writerow(["список", "id", "имя", "филиал", "дней", "последний", "заморозка_дней"])
    for key in ("soft", "call"):
        for x in r[key]:
            w.writerow([key, x["id"], x["имя"], x["филиал"], x["дней"], x["последний"], x["заморозка_дней"]])
    for why, n in r["skipped"].items():
        print(f"Пропущено: {why} — {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
