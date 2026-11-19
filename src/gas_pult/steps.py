"""Экран «Шаги» (GAS-16, слой 7; владелец 17.11: «возьми и примени всё»): что агент делал в чате — для отладки и
доверия. Из журнала Claude Code: сообщение человека → инструменты (что сделал, удачно ли, кусок результата) →
ответ. Секреты в тексте скрываются тем же правилом, что в строке статуса (``activity.mask``). Только чтение,
только стандартная библиотека; хвост журнала — не больше ``TAIL`` байт.
"""

from __future__ import annotations

from pathlib import Path

from gas_pult import activity, transcripts

TAIL = 4 * 1024 * 1024          # байт хвоста журнала: последние десятки ходов
TURNS = 40                      # ходов в ответе
OUT = 300                       # знаков результата инструмента
PROMPT = 400                    # знаков сообщения человека и ответа


def _text(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return "\n".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in v)
    return "" if v is None else str(v)


def _short(text: str, n: int) -> str:
    t = activity.mask(" ".join(str(text or "").split()))
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def turns(f: Path | None, q: str = "", limit: int = TURNS) -> list[dict]:
    """Ходы чата, новые сверху: {at, prompt, steps: [{at, tool, what, ok, out}], answer, dur}. ``q`` — поиск по
    сообщению, шагам, результатам и ответу (без учёта регистра)."""
    if not f:
        return []
    out: list[dict] = []
    cur: dict | None = None
    tools: dict[str, dict] = {}
    for e in activity.read_tail(f, TAIL):
        if e.get("isSidechain"):
            continue
        at = activity.stamp(e.get("timestamp", ""))
        kind = e.get("type")
        if kind == "user" and transcripts.is_real_prompt(e):
            text = transcripts.PASTED.sub("", transcripts.text_of((e.get("message") or {}).get("content")))
            cur = {"at": at, "prompt": _short(text, PROMPT), "steps": [], "answer": "", "end": at}
            out.append(cur)
            continue
        if cur is None:
            continue
        for b in activity._blocks(e):
            if kind == "assistant" and b.get("type") == "tool_use":
                name = str(b.get("name", ""))
                st = {"at": at, "tool": name, "what": activity.describe(name, b.get("input")), "ok": None, "out": ""}
                tools[str(b.get("id", ""))] = st
                cur["steps"].append(st)
            elif kind == "assistant" and b.get("type") == "text" and b.get("text", "").strip():
                cur["answer"] = _short(b["text"], PROMPT)
            elif kind == "user" and b.get("type") == "tool_result" and (st := tools.get(str(b.get("tool_use_id", "")))):
                st["ok"] = not b.get("is_error")
                st["out"] = _short(_text(b.get("content")), OUT)
                st["dur"] = round(max(0.0, at - st["at"]), 1)
        cur["end"] = max(cur["end"], at)
    for t in out:
        t["dur"] = round(max(0.0, t.pop("end") - t["at"]), 1)
    if q := " ".join(str(q or "").lower().split()):
        hay = lambda t: " ".join([t["prompt"], t["answer"], *(s["what"] + " " + s["out"] for s in t["steps"])])  # noqa: E731
        out = [t for t in out if q in hay(t).lower()]
    return list(reversed(out))[:limit]
