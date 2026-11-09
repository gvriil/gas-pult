"""Какими функциями панели пользуются: экран, лист, действие → когда открывали последний раз и сколько раз за месяц.

Зачем: раз в месяц (1-го числа, ``bot.digest_loop``) — отчёт владельцу в Telegram и файлом
``<данные>/usage-ГГГГ-ММ.md``: что не открывали 30 дней (кандидаты убрать) и что в ходу. Вручную —
``gas-pult usage report``.

Что храним (``features.json``, 0600): только id функции (``home.projects``, ``sheet.focus``, ``act:say``) → время
последнего открытия и счётчики по дням за последние 40 дней. Без людей, текста, адресов. Одна функция
записывается не чаще раза в минуту (``EVERY``): «открыли» — это минута, в которую ей пользовались.
Каталог для «не открывали» — экраны карты помощника (``help/screens.toml``): они же — экраны и листы панели.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from gas_pult.config import write_private

EVERY = 60                              # с: одна функция — не чаще раза в минуту
KEEP_DAYS = 40                          # счётчики по дням — с запасом на «за 30 дней»
WINDOW = 30                             # дней: «не открывали» и «топ за месяц»
ID = re.compile(r"^[a-z][a-z0-9_.:-]{1,60}$")
MAX_IDS = 20                            # за один запрос панели


class Uses:
    def __init__(self, store: Path):
        self.store, self.lock = store, threading.Lock()
        self.seen: dict[str, float] = {}       # id → когда записали (в памяти: без чтения файла на каждый запрос)

    def _load(self) -> dict:
        try:
            d = json.loads(self.store.read_text())
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def record(self, ids, now: float | None = None) -> int:
        """Отметить открытие функций: только допустимые id, каждая — не чаще раза в ``EVERY``. Сколько записали."""
        now = time.time() if now is None else now
        fresh = []
        for x in list(ids or [])[:MAX_IDS]:
            x = str(x or "")
            if ID.match(x) and now - self.seen.get(x, 0) >= EVERY and x not in fresh:
                fresh.append(x)
        if not fresh:
            return 0
        day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        cut = (datetime.fromtimestamp(now) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
        with self.lock:
            d = self._load()
            for x in fresh:
                rec = d.get(x) if isinstance(d.get(x), dict) else {}
                days = {k: v for k, v in (rec.get("days") or {}).items() if k >= cut}
                days[day] = int(days.get(day, 0)) + 1
                d[x] = {"last": int(now), "days": days}
                self.seen[x] = now
            write_private(self.store, json.dumps(d, ensure_ascii=False, sort_keys=True))
        return len(fresh)

    def stats(self, now: float | None = None) -> dict[str, dict]:
        """id → {last, month}: последнее открытие и сколько раз за ``WINDOW`` дней."""
        now = time.time() if now is None else now
        cut = (datetime.fromtimestamp(now) - timedelta(days=WINDOW)).strftime("%Y-%m-%d")
        return {k: {"last": int(v.get("last") or 0),
                    "month": sum(int(n) for day, n in (v.get("days") or {}).items() if day > cut)}
                for k, v in self._load().items() if isinstance(v, dict)}


def catalog() -> dict[str, str]:
    """Функции панели для отчёта: экраны и листы карты помощника — id → название."""
    from gas_pult import helper

    return {k: s.get("title") or k for k, s in helper.the_map()["screens"].items() if s.get("where") == "panel"}


def report(uses: Uses, now: float | None = None, top: int = 15, month: str = "") -> dict:
    """{month, unused: [(id, название, последний раз | None)], top: [(id, название, раз за месяц)], since}.
    ``month`` — подпись отчёта (по умолчанию — текущий месяц; 1-го числа бот подписывает прошлым)."""
    now = time.time() if now is None else now
    st, cat = uses.stats(now), catalog()
    old = now - WINDOW * 86400
    unused = sorted(((k, t, st.get(k, {}).get("last") or None) for k, t in cat.items()
                     if (st.get(k, {}).get("last") or 0) < old), key=lambda x: (x[2] or 0, x[0]))
    used = sorted(((k, cat.get(k, k), v["month"]) for k, v in st.items() if v["month"]), key=lambda x: (-x[2], x[0]))
    first = min((v["last"] for v in st.values() if v["last"]), default=None)
    return {"month": month or datetime.fromtimestamp(now).strftime("%Y-%m"), "unused": unused, "top": used[:top],
            "total": len(cat), "seen": len(st), "since": first}


def _day(ts: int | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y") if ts else "ни разу"


def markdown(r: dict) -> str:
    lines = [f"# Функции панели — отчёт за {r['month']}", "",
             f"Функций в каталоге: {r['total']}. Не открывали {WINDOW} дней: {len(r['unused'])}. "
             f"Учёт открытий — без людей и текста, функция — не чаще раза в минуту.", "",
             f"## Не открывали {WINDOW} дней — кандидаты убрать или спрятать", ""]
    lines += [f"- `{k}` — {t} (последний раз: {_day(last)})" for k, t, last in r["unused"]] or ["- таких нет"]
    lines += ["", f"## Чаще всего за {WINDOW} дней", ""]
    lines += [f"{i}. `{k}` — {t}: {n}" for i, (k, t, n) in enumerate(r["top"], 1)] or ["- пока нет данных"]
    return "\n".join(lines) + "\n"


def telegram(r: dict, path: Path | None = None) -> str:
    """Коротко — в Telegram; полный список — в файле."""
    un = r["unused"]
    head = f"📊 Функции панели за {r['month']}: не открывали {WINDOW} дней — {len(un)} из {r['total']}."
    body = [head, ""]
    if un:
        body += ["Не открывали:", *[f"• {t}" for _, t, _ in un[:12]]]
        if len(un) > 12:
            body.append(f"…и ещё {len(un) - 12}")
    if r["top"]:
        body += ["", "Чаще всего:"] + [f"• {t} — {n}" for _, t, n in r["top"][:5]]
    if path:
        body += ["", f"Полный отчёт: {path.name} (папка данных пульта)."]
    return "\n".join(body)


def write(data: Path, r: dict) -> Path:
    path = data / f"usage-{r['month']}.md"
    write_private(path, markdown(r))
    return path


def due(data: Path, now: datetime) -> bool:
    """Отчёт за прошлый месяц — 1-го числа, один раз: отметка ``features-sent.json``."""
    if now.day != 1:
        return False
    try:
        sent = json.loads((data / "features-sent.json").read_text()).get("month")
    except (OSError, ValueError, AttributeError):
        sent = None
    return sent != now.strftime("%Y-%m")


def mark_sent(data: Path, now: datetime):
    write_private(data / "features-sent.json", json.dumps({"month": now.strftime("%Y-%m"), "at": int(now.timestamp())}))


def previous(now: datetime) -> str:
    """Подпись отчёта 1-го числа — прошлый месяц: «2026-10» для 1 ноября."""
    return (date(now.year, now.month, 1) - timedelta(days=1)).strftime("%Y-%m")
