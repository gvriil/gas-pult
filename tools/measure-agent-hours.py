#!/usr/bin/env python3
"""Замер пользы пульта по журналам — без оценок «на глаз» (docs/PRODUCT.md, раздел «Цифра пользы»).

Что считает за период (по умолчанию — 7 полных дней до сегодняшней полуночи):
1. Часы работы агентов: сумма ходов Claude Code в журналах ``~/.claude/projects`` (ход — от сообщения человека до
   последней записи агента перед следующим сообщением человека). Отдельно — ходы дольше 5 минут: в это время без
   пульта человек ждал бы у экрана. Плановые запуски (``claude -p``) — отдельной строкой. Ход дольше 4 часов
   обрезается до 4 часов (забытое окно не раздувает цифру).
2. Доля сообщений агентам, отправленных через пульт: записи журнала доставок пульта ``sends.jsonl`` (панель, бот,
   фокус-ссылка) против сообщений человека в журналах Claude Code за те же дни. ``sends.jsonl`` ведётся с 10.11.2026.

Только чтение. Текст сообщений не выводится и не сохраняется. Только стандартная библиотека.

    python3 tools/measure-agent-hours.py                      # 7 дней до сегодня
    python3 tools/measure-agent-hours.py --end 2026-11-13 --days 7
    python3 tools/measure-agent-hours.py --sends-from 2026-11-11 --sends-to 2026-11-13
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import date, datetime
from pathlib import Path

CAP = 4 * 3600          # ход дольше — обрезаем
LONG = 5 * 60           # «долгий» ход: без пульта человек ждал бы у экрана
HUMAN_SRC = {"panel", "bot", "focus"}


def stamp(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def midnight(d: str) -> float:
    return datetime.combine(date.fromisoformat(d), datetime.min.time()).astimezone().timestamp()


def is_human(e: dict) -> bool:
    if e.get("type") != "user" or e.get("isMeta"):
        return False
    c = (e.get("message") or {}).get("content")
    if isinstance(c, str):
        return True
    if not isinstance(c, list):
        return False
    kinds = {b.get("type") for b in c if isinstance(b, dict)}
    return "text" in kinds and "tool_result" not in kinds


def turns(root: str, start: float, end: float) -> list[tuple[float, float, bool]]:
    """(начало хода, длительность, плановый запуск) — ходы, начатые в [start, end)."""
    out = []
    for f in glob.glob(os.path.join(root, "*", "*.jsonl")):
        if os.path.getmtime(f) < start:
            continue
        batch, cur, last = False, None, None
        try:
            lines = Path(f).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            batch = batch or e.get("entrypoint") == "sdk-cli"
            if e.get("isSidechain") or "timestamp" not in e:
                continue
            t = stamp(e["timestamp"])
            if is_human(e):
                if cur is not None and last:
                    out.append((cur, last - cur, batch))
                cur, last = t, None
            elif e.get("type") == "assistant" and cur is not None:
                last = t
        if cur is not None and last:
            out.append((cur, last - cur, batch))
    return [x for x in out if start <= x[0] < end and x[1] > 0]


def hours(xs) -> float:
    return sum(min(d, CAP) for _, d, _ in xs) / 3600


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--end", default=date.today().isoformat(), help="конец периода (полночь), ГГГГ-ММ-ДД")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--claude", default=os.path.expanduser("~/.claude/projects"), help="журналы Claude Code")
    ap.add_argument("--sends", default=os.path.expanduser("~/.local/share/gas-pult/sends.jsonl"))
    ap.add_argument("--sends-from", help="начало сверки доли через пульт (по умолчанию — начало периода)")
    ap.add_argument("--sends-to", help="конец сверки (по умолчанию — конец периода)")
    a = ap.parse_args(argv)
    end = midnight(a.end)
    start = end - a.days * 86400
    ts = turns(a.claude, start, end)
    inter, batch = [x for x in ts if not x[2]], [x for x in ts if x[2]]
    long = [x for x in inter if x[1] > LONG]
    fmt = lambda t: datetime.fromtimestamp(t).strftime("%d.%m.%Y %H:%M")   # noqa: E731
    print(f"Период: {fmt(start)} — {fmt(end)} ({a.days} дн.)")
    print(f"Ходов агентов (по сообщению человека): {len(inter)}; часов работы агентов: {hours(inter):.1f}")
    print(f"  из них ходов дольше {LONG // 60} мин: {len(long)}; их часы: {hours(long):.1f}")
    print(f"Плановых запусков (claude -p): {len(batch)}; часов: {hours(batch):.1f}")
    s0 = midnight(a.sends_from) if a.sends_from else start
    s1 = midnight(a.sends_to) if a.sends_to else end
    try:
        rows = [json.loads(x) for x in Path(a.sends).read_text(encoding="utf-8").splitlines() if x.strip()]
    except OSError:
        rows = []
    via = [r for r in rows if s0 <= r.get("ts", 0) < s1 and r.get("src") in HUMAN_SRC]
    msgs = [x for x in turns(a.claude, s0, s1) if not x[2]]
    if rows and msgs:
        print(f"Сверка {fmt(s0)} — {fmt(s1)}: сообщений человека агентам {len(msgs)}, из них через пульт "
              f"{len(via)} ({100 * len(via) / len(msgs):.0f} %)")
    else:
        print("Сверка доли через пульт: нет данных (журнал доставок пульта пуст или нет сообщений)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
