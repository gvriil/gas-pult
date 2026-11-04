"""«У поставщика закончились деньги» (задача 37): распознать ответ поставщика и не предлагать его, пока не пополнят.

Прямой ключ Z.ai при нулевом балансе отвечает 429 с кодом 1113 («Insufficient balance»), DeepSeek — 402
(«Insufficient Balance»). Claude Code пишет это строкой «API Error: …» в окне и ждёт — сам по себе чат «висит».

- ``NO_MONEY`` — такие ответы (на экране окна и в журнале).
- Отметка «без денег» — в ``state.json`` (``no_balance``: профиль → когда заметили) на ``TTL`` (час): столько профиль
  не предлагается в выборе поставщика; потом — снова (проверка раз в час). У DeepSeek есть бесплатный запрос баланса —
  его спрашиваем раз в час и сразу снимаем или ставим отметку. «Я пополнил» в панели снимает отметку сразу.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

TTL = 3600
NO_MONEY = re.compile(r'"code"\s*:\s*"?1113\b|insufficient[ _](account[ _])?balance|API Error:\s*402\b|'
                      r"Payment Required|余额不足", re.I)
BALANCE_URL = {"deepseek": "https://api.deepseek.com/user/balance"}


def seen(text: str) -> bool:
    return bool(NO_MONEY.search(str(text or "")))


def marked(state: dict, now: float | None = None) -> dict[str, float]:
    """Профили «без денег», отмеченные меньше часа назад."""
    now = time.time() if now is None else now
    return {p: t for p, t in (state.get("no_balance") or {}).items() if now - float(t) < TTL}


def mark(state: dict, profile: str, now: float | None = None) -> dict | None:
    """Новая отметка для ``state.json`` (None — уже отмечен в этот час, писать не нужно)."""
    now = time.time() if now is None else now
    cur = marked(state, now)
    if profile in cur:
        return None
    return {**cur, profile: now}


def clear(state: dict, profile: str) -> dict:
    return {p: t for p, t in marked(state).items() if p != profile}


def check(provider: str, key: str, opener=urllib.request.urlopen) -> bool | None:
    """Есть ли деньги (бесплатный запрос баланса): True / False; проверить нечем или не вышло — None."""
    url = BALANCE_URL.get(provider)
    if not url or not key:
        return None
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with opener(req, timeout=15) as r:
            d = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return False if e.code == 402 else None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    if "is_available" in d:
        return bool(d["is_available"])
    return None
