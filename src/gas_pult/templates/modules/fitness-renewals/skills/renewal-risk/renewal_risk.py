"""Продления клубных карт: точки касания до конца карты (60/30/7 дней), оценка риска «не продлит», персональное
и семейное предложение. Только стандартная библиотека; ничего не отправляет и не записывает.

Участники: data/members.csv — id, имя, телефон, канал, family_id, плательщик, тип_карты, филиал, карта_по,
согласие_уведомления, согласие_реклама, отписка, последнее_сообщение, точки_отправлены («60;30»), без_ответа (сколько
наших сообщений подряд без ответа). Посещения: data/visits.csv — дата, клиент_id, филиал, занятие.

Точка касания — самое узкое окно, в которое попал остаток дней: при 45 днях до конца — точка 60, при 20 — 30, при
5 — 7. Каждая точка — один раз (поле точки_отправлены). Риск: нет посещений 30 дней (+3) или посещаемость упала
вдвое против прошлых 30 дней (+2); до конца карты 7 дней и меньше (+2) или 30 и меньше (+1); без ответа на наши
сообщения (+1). 4 и больше — «высокий», 2–3 — «средний».

    python3 renewal_risk.py --today 2026-11-02 [--members data/members.csv] [--visits data/visits.csv] \\
        [--points 60,30,7] [--family-window 30] [--out outbox/renewals-plan.csv]
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from pathlib import Path

YES = {"да", "yes", "1", "true"}
EXPIRED_DAYS = 14               # карта кончилась недавно — ещё в списке «под риском» менеджеру


def yes(v: str | None) -> bool:
    return (v or "").strip().lower() in YES


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def parse_points(s: str) -> list[int]:
    """«60,30,7» → [60, 30, 7] (по убыванию, без повторов)."""
    pts = sorted({int(x) for x in str(s).replace(";", ",").split(",") if x.strip()}, reverse=True)
    if not pts or pts[-1] < 0:
        raise ValueError("точки касания — положительные числа дней, например 60,30,7")
    return pts


def stage(days_left: int, points: list[int]) -> int | None:
    """Самое узкое окно, в которое попал остаток: 45 → 60, 20 → 30, 5 → 7; больше первой точки или карта
    кончилась — None."""
    if days_left < 0:
        return None
    inside = [p for p in points if days_left <= p]
    return min(inside) if inside else None


def visit_stats(visits: list[dict], cid: str, today: date) -> dict:
    days = sorted(date.fromisoformat(v["дата"]) for v in visits if v["клиент_id"] == cid and v.get("дата"))
    days = [d for d in days if d <= today]
    last30 = sum(1 for d in days if today - timedelta(days=30) < d)
    prev30 = sum(1 for d in days if today - timedelta(days=60) < d <= today - timedelta(days=30))
    return {"за_30": last30, "прошлые_30": prev30, "последний": days[-1].isoformat() if days else ""}


def risk(m: dict, st: dict, today: date) -> tuple[int, str, list[str]]:
    score, why = 0, []
    if st["за_30"] == 0:
        score += 3
        why.append("нет посещений 30 дней")
    elif st["прошлые_30"] and st["за_30"] * 2 <= st["прошлые_30"]:
        score += 2
        why.append(f"посещений меньше вдвое: {st['прошлые_30']} → {st['за_30']}")
    left = (date.fromisoformat(m["карта_по"]) - today).days
    if left < 0:
        score += 2
        why.append(f"карта кончилась {-left} дн. назад")
    elif left <= 7:
        score += 2
        why.append(f"до конца карты {left} дн.")
    elif left <= 30:
        score += 1
        why.append(f"до конца карты {left} дн.")
    silent = int(m.get("без_ответа") or 0)
    if silent:
        score += 1
        why.append(f"без ответа на {silent} сообщ.")
    return score, "высокий" if score >= 4 else "средний" if score >= 2 else "низкий", why


def offer(m: dict, st: dict) -> str:
    """Персональное предложение — по посещаемости и типу карты; цены и скидки — только из прайса и [settings]."""
    per_week = (st["за_30"] + st["прошлые_30"]) / (60 / 7)
    kind = m.get("тип_карты") or "карта"
    if per_week >= 2:
        return f"продление «{kind}» на тот же срок — ходит {per_week:.1f} раза в неделю"
    if per_week >= 0.5:
        return f"продление «{kind}»; напомнить о групповых занятиях — ходит {per_week:.1f} раза в неделю"
    return "карта поменьше или дневная (по прайсу) и вводная с тренером — ходит редко"


def families(members: list[dict], today: date, window: int) -> dict[str, list[dict]]:
    """family_id → действующие карты семьи, которые кончаются в пределах window дней друг от друга (две и больше)."""
    by: dict[str, list[dict]] = {}
    for m in members:
        if m.get("family_id") and (date.fromisoformat(m["карта_по"]) - today).days >= 0:
            by.setdefault(m["family_id"], []).append(m)
    out = {}
    for fid, ms in by.items():
        ends = sorted(date.fromisoformat(m["карта_по"]) for m in ms)
        if len(ms) >= 2 and (ends[-1] - ends[0]).days <= window:
            out[fid] = ms
    return out


def plan(members: list[dict], visits: list[dict], today: date, points: list[int], family_window: int = 30) -> dict:
    """→ {"touches", "risk", "skipped"}. touches: кому и в какой точке пишем (семья — одно сообщение плательщику)."""
    fam = families(members, today, family_window)
    in_family = {m["id"]: fid for fid, ms in fam.items() for m in ms}
    out: dict = {"touches": [], "risk": [], "skipped": {}}

    def skip(why: str):
        out["skipped"][why] = out["skipped"].get(why, 0) + 1

    for m in members:
        st = visit_stats(visits, m["id"], today)
        left = (date.fromisoformat(m["карта_по"]) - today).days
        score, level, why = risk(m, st, today)
        if -EXPIRED_DAYS <= left <= points[0] and level != "низкий":
            out["risk"].append({"id": m["id"], "имя": m["имя"], "филиал": m.get("филиал", ""), "дней": left,
                                "балл": score, "риск": level, "почему": "; ".join(why)})
        p = stage(left, points)
        if p is None:
            continue
        done = {x.strip() for x in (m.get("точки_отправлены") or "").split(";") if x.strip()}
        if str(p) in done:
            continue
        fid = in_family.get(m["id"])
        if fid:
            payer = next((x for x in fam[fid] if yes(x.get("плательщик"))), fam[fid][0])
            if payer["id"] != m["id"]:
                skip("в семейном сообщении плательщику")
                continue
        if yes(m.get("отписка")) or not yes(m.get("согласие_уведомления")):
            skip("нет согласия на уведомления или отписка")
            continue
        ad = yes(m.get("согласие_реклама"))
        out["touches"].append({
            "id": m["id"], "имя": m["имя"], "филиал": m.get("филиал", ""), "точка": p, "дней": left,
            "семья": ",".join(x["id"] for x in fam[fid]) if fid else "",
            # Напоминание о конце карты — сервисное; предложение с условиями — только с согласием на рекламу.
            "предложение": (("семейное продление; " if fid else "") + offer(m, st)) if ad else "",
            "риск": level})
    out["risk"].sort(key=lambda r: (-r["балл"], r["дней"]))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Продления карт: точки 60/30/7, риск, предложения")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--members", type=Path, default=Path("data/members.csv"))
    ap.add_argument("--visits", type=Path, default=Path("data/visits.csv"))
    ap.add_argument("--points", default="60,30,7")
    ap.add_argument("--family-window", type=int, default=30)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    r = plan(read(a.members), read(a.visits), date.fromisoformat(a.today), parse_points(a.points), a.family_window)
    f = a.out.open("w", encoding="utf-8", newline="") if a.out else sys.stdout
    w = csv.writer(f)
    w.writerow(["id", "имя", "филиал", "точка", "дней", "семья", "предложение", "риск"])
    for t in r["touches"]:
        w.writerow([t[k] for k in ("id", "имя", "филиал", "точка", "дней", "семья", "предложение", "риск")])
    for x in r["risk"]:
        print(f"Под риском: {x['имя']} · {x['филиал']} · {x['риск']} ({x['балл']}): {x['почему']}", file=sys.stderr)
    for why, n in r["skipped"].items():
        print(f"Пропущено: {why} — {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
