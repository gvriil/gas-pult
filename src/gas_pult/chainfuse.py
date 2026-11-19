"""Предохранитель цепочек (GAS-25 п.3; штаб 19.11): две сессии пишут друг другу «пинг-понгом» — A→B, B→A, … — больше
``LIMIT`` раз подряд, каждое следующее сообщение не позже ``GAP`` секунд после предыдущего, и за это время ни в одном из
двух окон не было сообщения человека. Это зацикливание агентов: тратит деньги и память, человек не видит.

Только обнаружение (решение штаба): отправителя не блокируем — в окно-получатель последнего сообщения Escape
(прерывает ход), штабу — текст в его окно (имя начинается на «shtap»; если штаб сам в паре — не вставляем), и всегда —
задача пульта «ждёт вас», срочно и важно, со ссылкой на окна. В Telegram владельцу — нет (системное — в штаб).

Что считаем сообщением агента: в журнале Claude Code запись ``user`` с ``origin.kind = "peer"`` (письмо другой
сессии) или запрос, которого нет в журнале доставок пульта (``sends.jsonl``) — вставлен не через пульт (tmux
send-keys). Сообщение человека — запрос, который вставил пульт (панель, бот, фокус, терминал).
"""

from __future__ import annotations

import json
from pathlib import Path

LIMIT = 8              # сообщений подряд — больше этого = цепочка
GAP = 120              # с: следующее сообщение пары не позже
TAIL = 524288          # байт хвоста журнала, который читаем
HUMAN_SRC = {"panel", "bot", "focus", "tty", "term", "button", "scheduler"}


def _ts(s: str) -> float:
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def read_events(f: Path, wid: str, since: float, human_sha: set[str]) -> list[tuple[float, str, str]]:
    """События окна из хвоста журнала Claude: (время, окно, "agent" | "human")."""
    from gas_pult import deliveries, transcripts
    out = []
    try:
        with open(f, "rb") as fh:
            fh.seek(max(0, f.stat().st_size - TAIL))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") != "user":
            continue
        t = _ts(d.get("timestamp", ""))
        if t < since:
            continue
        if (d.get("origin") or {}).get("kind") == "peer":
            out.append((t, wid, "agent"))
            continue
        if not transcripts.is_real_prompt(d):
            continue
        text = transcripts.text_of((d.get("message") or {}).get("content")).strip()
        out.append((t, wid, "human" if deliveries.sha(text) in human_sha else "agent"))
    return out


def detect(events: list[tuple[float, str, str]], limit: int = LIMIT, gap: float = GAP) -> list[dict]:
    """Пинг-понги: [{a, b, n, last, at}] — пара окон, сколько сообщений подряд, кому пришло последнее, когда.
    Следующее сообщение идёт в другое окно той же пары (A, B, A, B…), не позже ``gap`` с, без человека в паре между."""
    agent = sorted((e for e in events if e[2] == "agent"), key=lambda e: e[0])
    humans = [e for e in events if e[2] == "human"]
    found: dict[frozenset, dict] = {}

    def link(p: tuple, e: tuple) -> bool:                 # e продолжает цепочку после p
        return (e[1] != p[1] and e[0] - p[0] <= gap
                and not any(p[0] <= h[0] <= e[0] and h[1] in (p[1], e[1]) for h in humans))

    run: list[tuple] = []
    for e in agent:
        if run and link(run[-1], e) and (len(run) < 2 or e[1] == run[-2][1]):
            run.append(e)
        else:
            run = [run[-1], e] if run and link(run[-1], e) else [e]
        if len(run) > limit:
            key = frozenset((run[0][1], run[1][1]))
            found[key] = {"a": run[0][1], "b": run[1][1], "n": len(run), "last": run[-1][1], "at": run[-1][0]}
    return list(found.values())
