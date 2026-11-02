"""Заявки в фитнес-клуб: свободные слоты экскурсии и вводной тренировки для ответа сразу (в том числе ночью) и
утренний «тёплый список» менеджеру. Только стандартная библиотека; ничего не отправляет и не записывает.

Заявки: data/leads.csv — id, получено (ГГГГ-ММ-ДДTЧЧ:ММ), источник, имя, контакт, филиал, интерес (экскурсия,
вводная или пусто), согласие_пдн, согласие_реклама, статус (новая, ответили, записан, отказ), слот.
Слоты: data/slots.csv — филиал, дата, время, вид (экскурсия, вводная), тренер, мест, занято.

    python3 lead_slots.py slots --lead 3 --now 2026-11-02T01:30 [--leads ...] [--slots ...] [--n 3] [--lead-hours 10]
    python3 lead_slots.py warm --now 2026-11-02T08:30 [--leads ...] [--hours 24]
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

KINDS = ("экскурсия", "вводная")
WARM_ORDER = {"новая": 0, "ответили": 1, "записан": 2}


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def at(s: dict) -> datetime:
    return datetime.fromisoformat(f"{s['дата']}T{s['время']}")


def free(slots: list[dict], kind: str, now: datetime, lead_hours: float = 10) -> list[dict]:
    """Слоты вида kind с местами, не раньше чем через lead_hours от now (ночью — уже утро с запасом)."""
    start = now + timedelta(hours=lead_hours)
    out = [s for s in slots if s["вид"] == kind and int(s.get("занято") or 0) < int(s.get("мест") or 0)
           and at(s) >= start]
    return sorted(out, key=at)


def propose(lead: dict, slots: list[dict], now: datetime, n: int = 3, lead_hours: float = 10) -> dict[str, list]:
    """Вид → до n слотов: сначала филиал заявки, потом остальные, по времени. Интерес пуст — оба вида."""
    kinds = [lead["интерес"]] if lead.get("интерес") in KINDS else list(KINDS)
    out = {}
    for k in kinds:
        cands = free(slots, k, now, lead_hours)
        own = [s for s in cands if s["филиал"] == lead.get("филиал")]
        out[k] = (own + [s for s in cands if s not in own])[:n]
    return out


def is_night(now: datetime, quiet_from: int = 21, quiet_to: int = 9) -> bool:
    return now.hour >= quiet_from or now.hour < quiet_to


def warm(leads: list[dict], now: datetime, hours: int = 24) -> list[dict]:
    """Тёплый список: заявки за последние hours часов без отказа. Сначала без ответа, потом без записи, потом
    записанные (подтвердить), внутри — по времени заявки."""
    since = now - timedelta(hours=hours)
    rows = [x | {"ночью": "да" if is_night(datetime.fromisoformat(x["получено"])) else ""} for x in leads
            if x.get("статус") != "отказ" and since <= datetime.fromisoformat(x["получено"]) <= now]
    return sorted(rows, key=lambda x: (WARM_ORDER.get(x.get("статус", ""), 3), x["получено"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Заявки: слоты для ответа и тёплый список")
    ap.add_argument("cmd", choices=("slots", "warm"))
    ap.add_argument("--now", default=datetime.now().strftime("%Y-%m-%dT%H:%M"))
    ap.add_argument("--leads", type=Path, default=Path("data/leads.csv"))
    ap.add_argument("--slots", type=Path, default=Path("data/slots.csv"))
    ap.add_argument("--lead", help="id заявки (для slots)")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--lead-hours", type=float, default=10)
    ap.add_argument("--hours", type=int, default=24)
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now)
    leads = read(a.leads)
    w = csv.writer(sys.stdout)
    if a.cmd == "slots":
        lead = next((x for x in leads if x["id"] == a.lead), None)
        if not lead:
            print(f"Нет заявки {a.lead}", file=sys.stderr)
            return 1
        w.writerow(["вид", "филиал", "дата", "время", "тренер", "свободно"])
        for k, ss in propose(lead, read(a.slots), now, a.n, a.lead_hours).items():
            for s in ss:
                w.writerow([k, s["филиал"], s["дата"], s["время"], s["тренер"], int(s["мест"]) - int(s["занято"])])
            if not ss:
                print(f"Нет свободных слотов: {k} — вопрос администратору", file=sys.stderr)
        return 0
    w.writerow(["id", "получено", "ночью", "источник", "имя", "филиал", "интерес", "статус", "слот"])
    for x in warm(leads, now, a.hours):
        w.writerow([x["id"], x["получено"], x["ночью"], x["источник"], x["имя"], x["филиал"], x["интерес"],
                    x["статус"], x.get("слот", "")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
