"""Разбиение текста для синтеза (без тяжёлых зависимостей — тестируется отдельно)."""

from __future__ import annotations

import re


def chunks(text: str, limit: int = 800) -> list[str]:
    """Silero берёт до ~1000 знаков за раз — режем по предложениям, длинные — по пробелам."""
    out, cur = [], ""
    for s in re.split(r"(?<=[.!?…])\s+|\n+", text):
        s = s.strip()
        if not s:
            continue
        while len(s) > limit:
            cut = s.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            out.append(s[:cut])
            s = s[cut:].strip()
        if cur and len(cur) + len(s) + 1 > limit:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    return [*out, cur] if cur else out
