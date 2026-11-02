"""Распределение пика сезонной переобувки по филиалам сети: кому какой свободный слот предложить.

Клиенты с хранением шин — в филиал, где лежат шины; нет слота или день перегружен — соседний филиал с пометкой
«нужна перевозка шин». Прошлые клиенты шиномонтажа (только с согласием на рекламу) — в менее загруженный из двух:
свой прошлый филиал или соседний. Загрузка дня = занятые слоты / все слоты филиала за день (так учитываются посты).
Отписавшиеся и без согласия — не попадают. Только стандартная библиотека; ничего не отправляет и не записывает.

    python3 peak_spread.py --clients data/clients.csv --slots data/slots.csv --branches data/branches.csv \\
        --from 2026-11-09 --to 2026-11-22 [--max-load 0.85] [--today 2026-11-02] [--out outbox/slots-plan.csv]
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

YES = {"да", "yes", "1", "true"}
PAST_DAYS = 400                 # «прошлый клиент шиномонтажа» — переобувался за два последних сезона


def yes(v: str | None) -> bool:
    return (v or "").strip().lower() in YES


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def segment(c: dict, today: date) -> str | None:
    """«хранение», «прошлый» или None (не пишем): отписка, нет согласия, давно не был."""
    if yes(c.get("отписка")):
        return None
    if yes(c.get("хранение_шин")) and c.get("договор_хранения") and c.get("филиал_хранения"):
        return "хранение" if yes(c.get("согласие_уведомления")) else None
    last = c.get("последний_шиномонтаж")
    if not last or not yes(c.get("согласие_реклама")):              # реклама — только с согласием (38-ФЗ, ст. 18)
        return None
    return "прошлый" if (today - date.fromisoformat(last)).days <= PAST_DAYS else None


class Board:
    """Слоты сети: свободные по филиалам и загрузка дня."""

    def __init__(self, slots: list[dict], start: date, end: date):
        self.free: dict[str, list[dict]] = {}
        self.total: dict[tuple[str, str], int] = {}
        self.busy: dict[tuple[str, str], int] = {}
        for s in slots:
            d = date.fromisoformat(s["дата"])
            if not start <= d <= end:
                continue
            k = (s["филиал"], s["дата"])
            self.total[k] = self.total.get(k, 0) + 1
            if yes(s.get("занят")):
                self.busy[k] = self.busy.get(k, 0) + 1
            else:
                self.free.setdefault(s["филиал"], []).append(s)
        for v in self.free.values():
            v.sort(key=lambda s: (s["дата"], s["время"], s["пост"]))

    def load(self, branch: str, day: str, extra: int = 0) -> float:
        t = self.total.get((branch, day), 0)
        return (self.busy.get((branch, day), 0) + extra) / t if t else 1.0

    def period_load(self, branch: str) -> float:
        t = sum(v for (b, _), v in self.total.items() if b == branch)
        return sum(v for (b, _), v in self.busy.items() if b == branch) / t if t else 1.0

    def first(self, branch: str, max_load: float) -> dict | None:
        """Самый ранний свободный слот, после которого загрузка дня не выше порога."""
        for s in self.free.get(branch, []):
            if self.load(branch, s["дата"], 1) <= max_load + 1e-9:
                return s
        return None

    def take(self, s: dict):
        self.free[s["филиал"]].remove(s)
        k = (s["филиал"], s["дата"])
        self.busy[k] = self.busy.get(k, 0) + 1


def plan(clients: list[dict], slots: list[dict], branches: list[dict], start: date, end: date,
         max_load: float = 0.85, today: date | None = None) -> tuple[list[dict], dict]:
    """→ (строки плана, итог). Строка: id, имя, сегмент, филиал, дата, время, пост, примечание."""
    today = today or date.today()
    near = {b["филиал"]: b.get("соседний", "") for b in branches}
    board = Board(slots, start, end)
    before = {b: round(board.period_load(b), 2) for b in near}
    rows, skipped = [], {"нет согласия или отписка": 0, "нет слота": 0}
    chosen = [(segment(c, today), c) for c in clients]
    for seg, c in sorted(chosen, key=lambda x: x[0] != "хранение"):  # хранение — первым: шины лежат у нас
        if seg is None:
            skipped["нет согласия или отписка"] += 1
            continue
        note = ""
        if seg == "хранение":
            home = c["филиал_хранения"]
            s = board.first(home, max_load)
            if s is None and (alt := near.get(home)):
                s, note = board.first(alt, max_load), f"нужна перевозка шин из «{home}»"
        else:
            home = c.get("филиал_последний", "")
            alt = near.get(home, "")
            order = sorted([b for b in (home, alt) if b in near], key=board.period_load)
            s = next((x for b in order if (x := board.first(b, max_load))), None)
        if s is None:
            skipped["нет слота"] += 1
            rows.append({"id": c["id"], "имя": c["имя"], "сегмент": seg, "филиал": "", "дата": "", "время": "",
                         "пост": "", "примечание": "нет свободного слота в окне — вопрос человеку"})
            continue
        board.take(s)
        rows.append({"id": c["id"], "имя": c["имя"], "сегмент": seg, "филиал": s["филиал"], "дата": s["дата"],
                     "время": s["время"], "пост": s["пост"], "примечание": note})
    after = {b: round(board.period_load(b), 2) for b in near}
    return rows, {"загрузка_до": before, "загрузка_после": after, "пропущено": skipped}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Распределить пик переобувки по филиалам")
    ap.add_argument("--clients", type=Path, required=True)
    ap.add_argument("--slots", type=Path, required=True)
    ap.add_argument("--branches", type=Path, required=True)
    ap.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    ap.add_argument("--to", dest="end", type=date.fromisoformat)
    ap.add_argument("--max-load", type=float, default=0.85)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    end = a.end or a.start + timedelta(days=13)
    rows, total = plan(read(a.clients), read(a.slots), read(a.branches), a.start, end, a.max_load, a.today)
    out = open(a.out, "w", encoding="utf-8", newline="") if a.out else sys.stdout  # noqa: SIM115
    w = csv.DictWriter(out, fieldnames=["id", "имя", "сегмент", "филиал", "дата", "время", "пост", "примечание"])
    w.writeheader()
    w.writerows(rows)
    if a.out:
        out.close()
    print(f"Загрузка до: {total['загрузка_до']}; после: {total['загрузка_после']}; "
          f"пропущено: {total['пропущено']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
