"""Яндекс Метрика для пульта: счётчики, сводка посещаемости за период (со сравнением с прошлым периодом), по дням,
источники трафика, цели и их достижения — только чтение. Записи нет вовсе: цели, счётчики, доступы не меняем.

Ключ — ``~/.config/gastech-mcp/metrika.token`` (путь — ``GAS_METRIKA_KEY_FILE``): JSON
``{"token": "<OAuth>", "counter": "<id счётчика>"}`` или просто OAuth-токен одной строкой (тогда счётчик — параметром
``counter``). Адрес — ``https://api-metrika.yandex.net``, ``GAS_METRIKA_BASE`` подменяет (тесты).
Контракт — docs/CONNECTORS.md. Документация — https://yandex.ru/dev/metrika/ru/ (сверено 22.11.2026 по индексу
Context7 «/websites/yandex_ru_dev_metrika_ru»: intro/authorization, intro/quotas, intro/quick-start,
management/openapi/counter/counters, management/openapi/goal/goals, stat/openapi/data_1, stat/examples,
stat/localize). **Не проверено на песочнице** — ключа ещё нет; песочницы у Метрики нет, токен всегда боевой
(право ``metrika:read`` — только чтение).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta

if __package__:
    from . import _core
else:                                                  # запуск файлом: python3 metrika_mcp.py
    import _core

SVC = "metrika"
NAME = "Яндекс Метрика"
# intro/quotas: 30 запросов в секунду с IP, 3 параллельных и 5000 в сутки на пользователя, к отчётам /stat/v1/data —
# 200 за 5 минут. Держим заметно ниже: 3 запроса в секунду.
THROTTLE = _core.Throttle(3, 1.0)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COUNTER = re.compile(r"^\d{1,12}$")
SUMMARY = (("visits", "ym:s:visits"), ("users", "ym:s:users"), ("pageviews", "ym:s:pageviews"),
           ("bounce_rate_pct", "ym:s:bounceRate"), ("avg_visit_sec", "ym:s:avgVisitDurationSeconds"),
           ("new_users_pct", "ym:s:percentNewVisitors"))
MAX_GOALS = 10                                          # по 2 метрики на цель, у отчёта ограничение на число метрик


def _creds() -> tuple[str, str, str]:
    raw = _core.read_secret(SVC)
    token, counter = raw, ""
    if raw.startswith("{"):
        try:
            d = json.loads(raw)
            token, counter = str(d["token"]).strip(), str(d.get("counter") or "").strip()
        except (ValueError, TypeError, KeyError):
            raise _core.ToolError('файл ключа metrika.token — JSON {"token": "...", "counter": "..."} или токен '
                                  "одной строкой, см. docs/connectors/metrika.md") from None
    if not token:
        raise _core.ToolError("в metrika.token пустой token")
    return token, counter, raw


def _secrets(token: str, raw: str) -> list[str]:
    """Прятать токен и файл целиком; номер счётчика — не секрет (``secret_values`` спрятал бы и его)."""
    return [raw, token]


def _keys() -> list[str]:
    token, _, raw = _creds()
    return _secrets(token, raw)


def _api(path: str, query: dict | None = None):
    token, _, raw = _creds()
    return _core.http("GET", _core.base_url(SVC, "https://api-metrika.yandex.net") + path,
                      headers={"Authorization": f"OAuth {token}"}, query=query,
                      keys=_secrets(token, raw), throttle=THROTTLE, service=NAME)


def _counter(a: dict) -> str:
    c = str(a.get("counter") or "").strip() or _creds()[1]
    if not c:
        raise _core.ToolError("не указан счётчик: параметр counter (id из metrika_list_counters) или поле counter "
                              "в metrika.token")
    if not _COUNTER.match(c):
        raise _core.ToolError("counter — номер счётчика цифрами")
    return c


def _day(s, what: str) -> date:
    if not _DATE.match(str(s)):
        raise _core.ToolError(f"{what}: дата в виде ГГГГ-ММ-ДД")
    return date.fromisoformat(s)


def _period(a: dict, default_days: int = 1, max_days: int = 366) -> tuple[date, date]:
    """Период по датам счётчика. По умолчанию — вчера (или последние N дней, заканчивая вчера)."""
    yesterday = date.today() - timedelta(days=1)
    d2 = _day(a["date_to"], "date_to") if a.get("date_to") else yesterday
    d1 = _day(a["date_from"], "date_from") if a.get("date_from") else d2 - timedelta(days=default_days - 1)
    if d2 < d1:
        raise _core.ToolError("date_to раньше date_from")
    if (d2 - d1).days + 1 > max_days:
        raise _core.ToolError(f"период — не больше {max_days} дней")
    return d1, d2


def _limit(a: dict, default: int = 20) -> int:
    return max(1, min(int(a.get("limit", default)), 100))


def _stat(counter: str, d1: date, d2: date, metrics: list[str], **kw) -> dict:
    q = {"ids": counter, "metrics": ",".join(metrics), "date1": d1.isoformat(), "date2": d2.isoformat(),
         "accuracy": "full", "lang": "ru", **kw}
    data = _api("/stat/v1/data", q)
    return data if isinstance(data, dict) else {}


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else round(f, 2)


def _named(keys, values) -> dict:
    return {k: _num(v) for k, v in zip(keys, values or [], strict=False)}


def _note(data: dict) -> dict:
    out = {}
    if data.get("sampled"):
        out["sampled"] = f"посчитано по выборке {_num((data.get('sample_share') or 0) * 100)} % визитов"
    if data.get("contains_sensitive_data"):
        out["privacy"] = "часть данных скрыта Метрикой (мало визитов) — цифры могут быть неполными"
    return out


def _dash(counter: str, report: str = "dashboard") -> str:
    # Формат ссылки — по адресу интерфейса Метрики, не из документации API.
    return f"https://metrika.yandex.ru/{report}?id={counter}"


# ---------- чтение ----------
def list_counters(a: dict):
    limit = _limit(a)
    q = {"per_page": limit}
    if a.get("search"):
        q["search_string"] = str(a["search"])[:100]
    data = _api("/management/v1/counters", q)
    rows = [{"id": c.get("id"), "name": c.get("name"), "site": (c.get("site2") or {}).get("site") or c.get("site"),
             "status": c.get("status"), "activity": c.get("activity_status"), "permission": c.get("permission"),
             "timezone": c.get("time_zone_name"), "link": _dash(str(c.get("id")))}
            for c in (data.get("counters") or [])[:limit]]
    out = {"total": data.get("rows"), "note": "permission: own — ваш, edit — можно править, view — только смотреть; "
           "id подставьте в counter или в metrika.token", "rows": rows}
    if (data.get("rows") or 0) > len(rows):
        out["more"] = f"показано {len(rows)} из {data['rows']}; уточните search"
    return out


def get_summary(a: dict):
    counter = _counter(a)
    d1, d2 = _period(a)
    span = (d2 - d1).days + 1
    p1, p2 = d1 - timedelta(days=span), d1 - timedelta(days=1)
    metrics = [m for _, m in SUMMARY]
    keys = [k for k, _ in SUMMARY]
    cur, prev = _stat(counter, d1, d2, metrics), _stat(counter, p1, p2, metrics)
    now, was = _named(keys, cur.get("totals")), _named(keys, prev.get("totals"))
    change = {k: (round((now[k] - was[k]) / was[k] * 100, 1) if now.get(k) is not None and was.get(k) else None)
              for k in ("visits", "users", "pageviews")}
    return {"counter": counter, "period": [d1.isoformat(), d2.isoformat()], **now,
            "previous": {"period": [p1.isoformat(), p2.isoformat()], **was}, "change_pct": change,
            "note": "даты — в часовом поясе счётчика; change_pct — к прошлому периоду той же длины", **_note(cur),
            "link": _dash(counter)}


def list_days(a: dict):
    counter = _counter(a)
    d1, d2 = _period(a, default_days=7, max_days=92)
    keys, metrics = ["visits", "users", "pageviews"], ["ym:s:visits", "ym:s:users", "ym:s:pageviews"]
    data = _stat(counter, d1, d2, metrics, dimensions="ym:s:date", sort="ym:s:date", limit=100)
    rows = [{"date": (r.get("dimensions") or [{}])[0].get("name"), **_named(keys, r.get("metrics"))}
            for r in data.get("data") or []]
    return {"counter": counter, "period": [d1.isoformat(), d2.isoformat()], "total": _named(keys, data.get("totals")),
            "note": "дней без визитов в списке нет", **_note(data), "rows": rows}


def list_sources(a: dict):
    counter = _counter(a)
    d1, d2 = _period(a, default_days=7)
    keys = ["visits", "users", "bounce_rate_pct"]
    data = _stat(counter, d1, d2, ["ym:s:visits", "ym:s:users", "ym:s:bounceRate"],
                 dimensions="ym:s:lastTrafficSource", sort="-ym:s:visits", limit=_limit(a, 10))
    rows = [{"source": d.get("name"), "source_id": d.get("id"), **_named(keys, r.get("metrics"))}
            for r in data.get("data") or [] for d in [(r.get("dimensions") or [{}])[0]]]
    return {"counter": counter, "period": [d1.isoformat(), d2.isoformat()], "total": _named(keys, data.get("totals")),
            "note": "источник — по последнему переходу (модель атрибуции «последний переход»)", **_note(data),
            "rows": rows, "link": _dash(counter, "stat/sources")}


def list_goals(a: dict):
    counter = _counter(a)
    d1, d2 = _period(a, default_days=7)
    goals = [g for g in (_api(f"/management/v1/counter/{counter}/goals").get("goals") or [])
             if str(g.get("id", "")).isdigit()]
    shown = goals[:MAX_GOALS]
    rows = [{"id": g.get("id"), "name": g.get("name"), "type": g.get("type")} for g in shown]
    out = {"counter": counter, "period": [d1.isoformat(), d2.isoformat()], "rows": rows,
           "note": "reaches — достижений цели, conversion_pct — доля визитов с достижением"}
    if shown:
        metrics = [m for g in shown for m in (f"ym:s:goal{g['id']}reaches", f"ym:s:goal{g['id']}conversionRate")]
        data = _stat(counter, d1, d2, metrics)
        tot = [_num(v) for v in data.get("totals") or []]
        for i, row in enumerate(rows):
            row["reaches"] = tot[2 * i] if 2 * i < len(tot) else None
            row["conversion_pct"] = tot[2 * i + 1] if 2 * i + 1 < len(tot) else None
        out.update(_note(data))
    else:
        out["note"] = "целей у счётчика нет — настройте их в интерфейсе Метрики (коннектор цели не создаёт)"
    if len(goals) > len(shown):
        out["more"] = f"показано {len(shown)} целей из {len(goals)}"
    return out


_PERIOD = {"counter": {"type": "string", "description": "id счётчика (по умолчанию — из metrika.token)"},
           "date_from": {"type": "string", "description": "ГГГГ-ММ-ДД"},
           "date_to": {"type": "string", "description": "ГГГГ-ММ-ДД включительно (по умолчанию — вчера)"}}

SERVER = {
    "name": f"gas-pult-{SVC}",
    "instructions": "Яндекс Метрика: посещаемость сайта, источники, цели — только чтение. Ничего не меняет: "
                    "ни счётчики, ни цели, ни доступы.",
    "keys": _keys,
    "tools": [
        {"name": f"{SVC}_list_counters",
         "description": "Счётчики Метрики, доступные по ключу: id, название, сайт, статус, ваши права. "
                        "Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {
             "search": {"type": "string", "description": "часть названия, адреса сайта или id"},
             "limit": {"type": "integer", "default": 20}}},
         "fn": list_counters},
        {"name": f"{SVC}_get_summary",
         "description": "Сводка посещаемости за период (по умолчанию — вчера): визиты, посетители, просмотры, "
                        "отказы, время на сайте, доля новых — и изменение к прошлому периоду той же длины в %. "
                        "Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": _PERIOD}, "fn": get_summary},
        {"name": f"{SVC}_list_days",
         "description": "Визиты, посетители и просмотры по дням (по умолчанию — 7 дней до вчера, не больше 92). "
                        "Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": _PERIOD}, "fn": list_days},
        {"name": f"{SVC}_list_sources",
         "description": "Откуда пришли посетители (поиск, реклама, ссылки, прямые заходы, соцсети…) за период "
                        "(по умолчанию — 7 дней): визиты, посетители, отказы. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {**_PERIOD,
                                                          "limit": {"type": "integer", "default": 10}}},
         "fn": list_sources},
        {"name": f"{SVC}_list_goals",
         "description": f"Цели счётчика (заявка, звонок, корзина…) и сколько раз их достигли за период (по "
                        f"умолчанию — 7 дней), конверсия в %. До {MAX_GOALS} целей. Цели не создаёт и не меняет.",
         "inputSchema": {"type": "object", "properties": _PERIOD}, "fn": list_goals}],
}

if __name__ == "__main__":
    sys.exit(_core.main(SERVER, SVC))
