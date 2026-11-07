"""Бюджет демо-пространства — запас на период, а не жёсткий лимит дня (задача 35).

Владелец задаёт норму в день (``daily_usd``, например $3–4); запас периода = норма × ``period_days`` (по умолчанию 30)
плюс пополнения. Тратить можно больше нормы в загруженные дни за счёт будущих, неистраченное остаётся в запасе.
Стоп — только когда запас периода исчерпан; по желанию — ещё потолок дня (``day_cap_x`` × норма, по умолчанию
выключен). Периоды идут подряд от ``start``: закончился — начинается новый с полным запасом.

Где что лежит:
- ``budget.json`` пространства (пишет ``pult-tenant create … --budget 4 --period 30 [--day-cap 3]``, root, 0640):
  ``daily_usd``, ``period_days``, ``start``, ``day_cap_x``. Старый вид ``{"daily_usd": 3}`` читается: период 30 дней от
  даты файла.
- Данные пульта ``space-budget/<slug>.json`` (0600; в пространство пульт писать не может): расход по дням (максимум
  увиденного — расход удалённой в корзину сессии не «возвращается»), пополнения «+ добавить», отметки «сообщили на
  80% / 100%».

Расход — по журналам Claude Code пространства (usage.py): модели Claude — по ценам API (на подписке это оценка,
``estimate``), OpenRouter — по счёту за каждый ответ, Z.ai и DeepSeek — оценка по токенам и тарифу поставщика
(``source`` = «estimate»). Цену Claude Code (по тарифам Anthropic для чужих моделей) не берём.
"""

from __future__ import annotations

import json
import threading
from datetime import date, timedelta
from pathlib import Path

from gas_pult.config import data_dir, write_private

PERIOD_DAYS = 30
WARN_AT = (0.8, 1.0)
_lock = threading.Lock()


def config(raw: dict | None, fallback_start: date | None = None) -> dict | None:
    """``budget.json`` → {daily, period_days, start, day_cap_x}; нормы нет — None. Старый вид — период 30 дней."""
    if not isinstance(raw, dict):
        return None
    try:
        daily = float(raw.get("daily_usd"))
    except (TypeError, ValueError):
        return None
    try:
        days = int(raw.get("period_days") or PERIOD_DAYS)
    except (TypeError, ValueError):
        days = PERIOD_DAYS
    try:
        start = date.fromisoformat(str(raw["start"]))
    except (KeyError, ValueError):
        start = fallback_start or date.today()
    cap = raw.get("day_cap_x")
    try:
        cap = float(cap) if cap not in (None, "", 0) else None
    except (TypeError, ValueError):
        cap = None
    return {"daily": max(daily, 0.0), "period_days": max(days, 1), "start": start, "day_cap_x": cap}


def period(cfg: dict, today: date) -> tuple[date, date]:
    """Текущий период: (первый день, последний день). Периоды идут подряд от ``start``."""
    n = cfg["period_days"]
    k = max((today - cfg["start"]).days, 0) // n
    first = cfg["start"] + timedelta(days=k * n)
    return first, first + timedelta(days=n - 1)


def state(cfg: dict, spent: dict[str, float], today: date, extra: float = 0.0, estimate: bool = False,
          source: str | None = None) -> dict:
    """Запас периода по расходу ``spent`` {«ГГГГ-ММ-ДД»: USD}. ``extra`` — пополнения этого периода. ``source`` —
    источник цены расхода (usage.source: «anthropic» | «provider» | «estimate» | None) — поле ``cost_source``."""
    first, last = period(cfg, today)
    reserve = round(cfg["daily"] * cfg["period_days"] + extra, 2)
    days = [first + timedelta(days=i) for i in range((today - first).days + 1)]
    used = round(sum(spent.get(d.isoformat(), 0.0) for d in days), 4)
    now = round(spent.get(today.isoformat(), 0.0), 4)
    left = round(reserve - used, 4)
    cap = round(cfg["day_cap_x"] * cfg["daily"], 2) if cfg.get("day_cap_x") else None
    reason = "period" if left <= 0 else "day" if cap is not None and now >= cap else ""
    pace = used / len(days) if days else 0.0              # средний расход в день с начала периода
    if left <= 0:
        until = today
    elif pace > 0:
        until = min(today + timedelta(days=int(left // pace)), last + timedelta(days=0))
    else:
        until = last
    return {"daily": cfg["daily"], "period_days": cfg["period_days"], "start": first.isoformat(),
            "end": last.isoformat(), "reserve": reserve, "spent": round(used, 2), "today": round(now, 2),
            "left": round(max(left, 0.0), 2), "day_cap": cap, "over": bool(reason), "reason": reason,
            "pct": round(used / reserve, 4) if reserve > 0 else 1.0, "pace": round(pace, 2),
            "enough_until": until.isoformat(), "enough_all": until >= last and left > 0, "estimate": estimate,
            "extra": round(extra, 2), "cost_source": source}


def text(b: dict, lang: str = "ru") -> str:
    """«сегодня $X · в запасе $Y до <дата> · норма $Z/день; при нынешнем темпе хватит до <дата>»."""
    d = lambda iso: date.fromisoformat(iso).strftime("%d.%m")       # noqa: E731
    tail = "до конца периода" if b["enough_all"] else f"до {d(b['enough_until'])}"
    s = (f"сегодня ${b['today']:.2f} · в запасе ${b['left']:.2f} до {d(b['end'])} · норма ${b['daily']:.2f}/день; "
         f"при нынешнем темпе хватит {tail}")
    if b["day_cap"] is not None:
        s += f" · потолок дня ${b['day_cap']:.2f}"
    if b.get("cost_source") == "estimate":
        return s + " (оценка: токены × цены поставщика)"
    if b.get("cost_source") == "provider" and not b["estimate"]:
        return s + " (по счёту OpenRouter)"
    return s + (" (оценка по ценам за токены — работает на подписке)" if b["estimate"] else "")


# ---------- данные пульта: расход по дням, пополнения, отметки ----------
def store(slug: str) -> Path:
    return data_dir() / "space-budget" / f"{slug}.json"


def load_store(slug: str) -> dict:
    try:
        d = json.loads(store(slug).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_store(slug: str, d: dict):
    p = store(slug)
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_private(p, json.dumps(d, ensure_ascii=False))


def remember(slug: str, seen: dict[str, float], keep_from: date) -> dict[str, float]:
    """Расход по дням: максимум из уже записанного и увиденного сейчас (удалённые журналы не уменьшают расход).
    Дни до ``keep_from`` (прошлые периоды) — убираем."""
    with _lock:
        d = load_store(slug)
        days = {k: float(v) for k, v in (d.get("days") or {}).items() if k >= keep_from.isoformat()}
        for k, v in seen.items():
            if k >= keep_from.isoformat() and v > days.get(k, 0.0) + 1e-9:
                days[k] = round(v, 4)
        if days != d.get("days"):
            d["days"] = days
            save_store(slug, d)
        return days


def extra(slug: str, first: date) -> float:
    """Пополнения текущего периода."""
    return round(sum(float(x.get("usd") or 0) for x in load_store(slug).get("topups") or []
                     if x.get("period") == first.isoformat()), 2)


def top_up(slug: str, usd: float, first: date, by: int | None = None, at: float | None = None) -> float:
    """«+ добавить»: пополнить запас текущего периода. Возвращает пополнения периода."""
    usd = round(float(usd), 2)
    if not 0 < usd <= 1000:
        raise ValueError("пополнение — от $0.01 до $1000")
    import time
    with _lock:
        d = load_store(slug)
        d.setdefault("topups", []).append({"usd": usd, "period": first.isoformat(), "at": int(at or time.time()),
                                           **({"by": int(by)} if by else {})})
        save_store(slug, d)
    return extra(slug, first)


def warn_due(slug: str, b: dict) -> float | None:
    """Порог (0.8 или 1.0), о котором ещё не сообщали в этом периоде, — и отметить его; иначе None."""
    hit = [x for x in WARN_AT if b["pct"] >= x]
    if not hit:
        return None
    with _lock:
        d = load_store(slug)
        told = d.setdefault("warned", {}).setdefault(b["start"], [])
        hit = [f"{x}@{b['reserve']}" for x in hit]              # пополнили запас — пороги считаются заново
        new = [x for x in hit if x not in told]
        if not new:
            return None
        told.extend(new)
        save_store(slug, d)
    return max(float(x.split("@")[0]) for x in new)
