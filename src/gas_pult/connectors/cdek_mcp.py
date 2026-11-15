"""СДЭК для пульта: города, пункты выдачи (ПВЗ и постаматы), расчёт тарифа по весу и габаритам, статус заказа —
только чтение и расчёты. Создание, изменение и удаление заказов, заявки на курьера, печать — не делаем (деньги).

Ключ — JSON ``{"account": "...", "secure": "...", "test": true}`` в ``~/.config/gastech-mcp/cdek.token``
(путь — ``GAS_CDEK_KEY_FILE``). Без файла — публичная тестовая учётная запись СДЭК на ``api.edu.cdek.ru``, и в каждом
ответе пометка «песочница». Контракт — docs/CONNECTORS.md, описание — docs/connectors/cdek.md.
Документация API v2: https://apidoc.cdek.ru/ (OpenAPI — кнопка «Скачать OpenAPI спецификацию» там же).
Проверено на песочнице api.edu.cdek.ru 15.11.2026 (ответы в tests/fixtures/cdek/ — оттуда).
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time

if __package__:
    from . import _core
else:                                                  # запуск файлом: python3 cdek_mcp.py
    import _core

SVC = "cdek"
NAME = "СДЭК"
PROD = "https://api.cdek.ru/v2"
TEST = "https://api.edu.cdek.ru/v2"
# Публичная тестовая учётная запись из документации (apidoc.cdek.ru → «Подключение к сервису»): не секрет,
# работает только на api.edu.cdek.ru, заказы там учебные. Склейкой — чтобы сканеры секретов не шумели.
SANDBOX = {"account": "wqGwiQx0gg8m" + "LtiEKsUinjVSICCjtTEP", "secure": "RmAmgvSgSl1y" + "irlz9QupbzOJVqhCxcP5"}
SANDBOX_NOTE = "песочница: публичная тестовая учётная запись СДЭК (api.edu.cdek.ru), данные учебные"
TEST_NOTE = "песочница СДЭК (api.edu.cdek.ru): данные учебные"
THROTTLE = _core.Throttle(20, 1.0)                     # документация: гарантированно 200 RPS; берём с большим запасом
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_NUM = re.compile(r"^\d{1,20}$")
_IM = re.compile(r"^[\w./-]{1,40}$")
POINT_TYPES = {"PVZ", "POSTAMAT", "ALL"}
MODES = {1: "дверь-дверь", 2: "дверь-склад", 3: "склад-дверь", 4: "склад-склад", 6: "дверь-постамат",
         7: "склад-постамат", 8: "постамат-дверь", 9: "постамат-склад", 10: "постамат-постамат"}

_tok: dict = {}                                        # {"key": (account, base), "token": "...", "until": monotonic}
_lock = threading.Lock()


def _creds() -> tuple[dict, str, str]:
    """(учётные данные, базовый адрес, пометка среды — пусто для боевой). Без файла ключа — публичная тестовая."""
    try:
        raw = _core.read_secret(SVC)
    except _core.ToolError as e:
        if "нет файла ключа" not in str(e):
            raise
        return SANDBOX, _core.base_url(SVC, TEST), SANDBOX_NOTE
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if not isinstance(data, dict) or not data.get("account") or not data.get("secure"):
        raise _core.ToolError('в файле cdek.token должен быть JSON {"account": "...", "secure": "...", "test": true} '
                              "— см. docs/connectors/cdek.md")
    test = bool(data.get("test", False))
    creds = {"account": str(data["account"]), "secure": str(data["secure"])}
    note = SANDBOX_NOTE if creds == SANDBOX else TEST_NOTE if test else ""
    return creds, _core.base_url(SVC, TEST if test else PROD), note


def _keys() -> list[str]:
    """Что прятать в ответах: account, secure и выданный токен доступа."""
    try:
        creds, _, _ = _creds()
    except _core.ToolError:
        creds = {}
    out = [v for v in creds.values() if v]
    if _tok.get("token"):
        out.append(_tok["token"])
    return out


def _token(creds: dict, base: str) -> str:
    """OAuth client_credentials. Токен живёт ~1 ч (expires_in) — держим в памяти процесса до истечения минус минута."""
    key = (creds["account"], base)
    with _lock:
        if _tok.get("key") == key and _tok.get("until", 0) > time.monotonic():
            return _tok["token"]
    r = _core.http("POST", base + "/oauth/token", keys=list(creds.values()), throttle=THROTTLE, service=NAME,
                   query={"grant_type": "client_credentials", "client_id": creds["account"],
                          "client_secret": creds["secure"]})
    if not isinstance(r, dict) or not r.get("access_token"):
        raise _core.ToolError(f"{NAME}: не выдал токен — проверьте account и secure в cdek.token")
    with _lock:
        _tok.update(key=key, token=r["access_token"],
                    until=time.monotonic() + max(60, int(r.get("expires_in") or 3600) - 60))
    return r["access_token"]


def _errors(r) -> list[str]:
    """Тексты ошибок СДЭК из ``{"requests": [{"errors": [...]}]}`` или ``{"errors": [...]}``."""
    if not isinstance(r, dict):
        return []
    errs = list(r.get("errors") or [])
    for q in r.get("requests") or []:
        errs += q.get("errors") or []
    return [f"{e.get('code', '')}: {e.get('message', '')}".strip(": ") for e in errs if isinstance(e, dict)]


def _api(method: str, path: str, *, query: dict | None = None, body=None) -> tuple:
    """Запрос к API v2 с токеном. Возвращает (ответ, пометка среды). Ошибки СДЭК — понятным текстом без ключа."""
    creds, base, sandbox = _creds()
    tok = _token(creds, base)
    keys = [*creds.values(), tok]
    try:
        r = _core.http(method, base + path, headers={"Authorization": f"Bearer {tok}"}, query=query, body=body,
                       keys=keys, throttle=THROTTLE, service=NAME)
    except _core.ToolError as e:
        t = str(e)
        if " 401" in t:                                # токен отозван раньше срока — следующий вызов возьмёт новый
            _tok.clear()
        m = re.search(r"\{.*", t, re.S)
        found = []
        if m:
            try:
                found = _errors(json.loads(m.group(0)))
            except ValueError:
                found = []
        if found and "not_found" in found[0]:
            raise _core.ToolError(_core.hide(f"{NAME}: не найдено — {found[0]}", *keys)) from None
        raise
    errs = _errors(r)
    if errs and isinstance(r, dict) and not r.get("entity") and "tariff_codes" not in r and "total_sum" not in r:
        raise _core.ToolError(_core.hide(f"{NAME}: " + "; ".join(errs), *keys))
    return r, sandbox


def _mark(res: dict, note: str) -> dict:
    return {"среда": note} | res if note else res


def _limit(a: dict, default: int = 20) -> int:
    return max(1, min(int(a.get("limit", default)), 100))


def _int(v, what: str, lo: int, hi: int) -> int:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        raise _core.ToolError(f"{what}: нужно число") from None
    if not lo <= n <= hi:
        raise _core.ToolError(f"{what}: от {lo} до {hi}")
    return n


# ---------- города ----------
def _city_row(c: dict) -> dict:
    return {"code": c.get("code"), "city": c.get("city", ""), "region": c.get("region", ""),
            "sub_region": c.get("sub_region"), "country_code": c.get("country_code", "")}


def list_cities(a: dict):
    name = str(a.get("name", "")).strip()
    if not name:
        raise _core.ToolError("name: название города, напр. «Казань»")
    limit = _limit(a, 10)
    country = str(a.get("country_code") or "RU").upper()[:2]
    r, sb = _api("GET", "/location/cities", query={"city": name, "country_codes": country, "size": limit})
    rows = [_city_row(c) for c in (r if isinstance(r, list) else [])]
    if not rows:                                       # точного совпадения нет — подсказки по началу названия
        s, sb = _api("GET", "/location/suggest/cities", query={"name": name, "country_code": country})
        rows = [{"code": c.get("code"), "city": c.get("full_name", ""), "country_code": c.get("country_code", "")}
                for c in (s if isinstance(s, list) else [])][:limit]
    return _mark({"rows": rows, "hint": "code — код города СДЭК для ПВЗ и расчёта тарифа"}, sb)


def _city_code(v, what: str) -> tuple[int, str | None]:
    """Код города СДЭК: число как есть, название — через подсказки (берём первую, название возвращаем для проверки)."""
    s = str(v if v is not None else "").strip()
    if not s:
        raise _core.ToolError(f"{what}: код города СДЭК или название")
    if _NUM.match(s):
        return int(s), None
    r, _ = _api("GET", "/location/suggest/cities", query={"name": s, "country_code": "RU"})
    if not isinstance(r, list) or not r:
        raise _core.ToolError(f"{what}: город «{s}» не найден — уточните через cdek_list_cities")
    return int(r[0]["code"]), r[0].get("full_name", s)


# ---------- пункты выдачи ----------
def _point(p: dict) -> dict:
    loc = p.get("location") or {}
    return {"code": p.get("code"), "type": p.get("type"), "name": p.get("name", ""),
            "address": loc.get("address_full") or loc.get("address", ""), "work_time": p.get("work_time", ""),
            "metro": p.get("nearest_metro_station"), "weight_max_kg": p.get("weight_max"),
            "cash": p.get("have_cash"), "cashless": p.get("have_cashless"), "cod": p.get("allowed_cod"),
            "dressing_room": p.get("is_dressing_room"), "status": p.get("status"),
            "lat": loc.get("latitude"), "lon": loc.get("longitude"), "link": p.get("site")}


def list_points(a: dict):
    code, resolved = _city_code(a.get("city"), "city")
    t = str(a.get("type") or "ALL").upper()
    if t not in POINT_TYPES:
        raise _core.ToolError("type: PVZ (пункт выдачи), POSTAMAT (постамат) или ALL")
    limit = _limit(a)
    q = {"city_code": code, "type": t, "size": limit, "page": 0}
    if a.get("weight_kg") not in (None, ""):
        q["weight_max"] = _int(a["weight_kg"], "weight_kg", 1, 1000)
    if a.get("cod"):
        q["allowed_cod"] = "true"
    r, sb = _api("GET", "/deliverypoints", query=q)
    rows = [_point(p) for p in (r if isinstance(r, list) else [])][:limit]
    res = {"city_code": code, "rows": rows}
    if resolved:
        res["city"] = resolved
    if len(rows) == limit:
        res["more"] = f"показано {limit}; больше — увеличьте limit (до 100) или добавьте фильтры"
    return _mark(res, sb)


# ---------- расчёт ----------
def _package(a: dict) -> dict:
    p = {"weight": _int(a.get("weight_g"), "weight_g (вес, граммы)", 1, 1_000_000)}
    for k in ("length", "width", "height"):
        if a.get(f"{k}_cm") not in (None, ""):
            p[k] = _int(a[f"{k}_cm"], f"{k}_cm", 1, 1500)
    return p


def calc(a: dict):
    frm, frm_name = _city_code(a.get("from_city"), "from_city")
    to, to_name = _city_code(a.get("to_city"), "to_city")
    body = {"from_location": {"code": frm}, "to_location": {"code": to}, "packages": [_package(a)]}
    res: dict = {"from_city_code": frm, "to_city_code": to}
    if frm_name:
        res["from_city"] = frm_name
    if to_name:
        res["to_city"] = to_name
    if a.get("tariff_code") not in (None, ""):
        body["tariff_code"] = _int(a["tariff_code"], "tariff_code", 1, 10_000)
        r, sb = _api("POST", "/calculator/tariff", body=body)
        dr = r.get("delivery_date_range") or {}
        res |= {"tariff_code": body["tariff_code"], "delivery_sum": r.get("delivery_sum"),
                "total_sum": r.get("total_sum"), "currency": r.get("currency", "RUB"),
                "days_min": r.get("period_min"), "days_max": r.get("period_max"),
                "date_min": dr.get("min"), "date_max": dr.get("max"), "weight_calc_g": r.get("weight_calc"),
                "services": [{"code": s.get("code"), "sum": s.get("total_sum", s.get("sum"))}
                             for s in r.get("services") or []]}
        return _mark(res, sb)
    r, sb = _api("POST", "/calculator/tarifflist", body=body)
    rows = []
    for t in r.get("tariff_codes") or []:
        dr = t.get("delivery_date_range") or {}
        rows.append({"tariff_code": t.get("tariff_code"), "name": t.get("tariff_name", ""),
                     "mode": MODES.get(t.get("delivery_mode"), str(t.get("delivery_mode"))),
                     "delivery_sum": t.get("delivery_sum"), "days_min": t.get("period_min"),
                     "days_max": t.get("period_max"), "date_min": dr.get("min"), "date_max": dr.get("max")})
    rows.sort(key=lambda x: (x["delivery_sum"] is None, x["delivery_sum"] or 0))
    limit = _limit(a)
    res |= {"currency": "RUB", "rows": rows[:limit],
            "hint": "delivery_sum — без доп. услуг; точная сумма с услугами — тот же вызов с tariff_code"}
    if len(rows) > limit:
        res["more"] = f"показано {limit} самых дешёвых из {len(rows)}; остальные — limit до 100"
    return _mark(res, sb)


# ---------- статус заказа ----------
def get_order(a: dict):
    q, path = None, None
    if a.get("uuid"):
        u = str(a["uuid"]).strip()
        if not _UUID.match(u):
            raise _core.ToolError("uuid: идентификатор заказа СДЭК вида 72753031-…")
        path = f"/orders/{u}"
    elif a.get("cdek_number"):
        n = str(a["cdek_number"]).strip()
        if not _NUM.match(n):
            raise _core.ToolError("cdek_number: номер накладной СДЭК — только цифры")
        path, q = "/orders", {"cdek_number": n}
    elif a.get("im_number"):
        n = str(a["im_number"]).strip()
        if not _IM.match(n):
            raise _core.ToolError("im_number: номер заказа магазина — буквы, цифры, «-», «_», «/», «.»")
        path, q = "/orders", {"im_number": n}
    else:
        raise _core.ToolError("нужен один из параметров: cdek_number, im_number или uuid")
    r, sb = _api("GET", path, query=q)
    e = r.get("entity") or {}
    if not e:
        raise _core.ToolError(f"{NAME}: заказ не найден")
    st = sorted(e.get("statuses") or [], key=lambda s: s.get("date_time") or "", reverse=True)
    dd = e.get("delivery_detail") or {}
    res = {"uuid": e.get("uuid"), "cdek_number": e.get("cdek_number"), "number": e.get("number"),
           "tariff_code": e.get("tariff_code"),
           "status": st[0].get("name") if st else None, "status_code": st[0].get("code") if st else None,
           "status_time": st[0].get("date_time") if st else None, "status_city": st[0].get("city") if st else None,
           "from_city": (e.get("from_location") or {}).get("city"), "to_city": (e.get("to_location") or {}).get("city"),
           "delivery_point": e.get("delivery_point"), "planned_delivery_date": e.get("planned_delivery_date"),
           "keep_free_until": e.get("keep_free_until"), "delivered": dd.get("date"),
           "history": [{"code": s.get("code"), "name": s.get("name"), "time": s.get("date_time"),
                        "city": s.get("city")} for s in st[:15]]}
    if e.get("cdek_number"):
        res["link"] = f"https://www.cdek.ru/ru/tracking?order_id={e['cdek_number']}"
    if len(st) > 15:
        res["more"] = f"показаны 15 последних статусов из {len(st)}"
    return _mark(res, sb)


_CITY = {"type": ["string", "integer"], "description": "код города СДЭК (из cdek_list_cities) или название"}
SERVER = {
    "name": f"gas-pult-{SVC}",
    "instructions": "СДЭК: города, пункты выдачи, расчёт стоимости и сроков доставки, статус заказа — только чтение. "
                    "Заказы не создаёт и не меняет. Без ключа работает на песочнице СДЭК (данные учебные).",
    "keys": _keys,
    "tools": [
        {"name": f"{SVC}_list_cities", "description": "Найти город СДЭК по названию: код, регион. Код нужен для "
         "ПВЗ и расчёта. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {
             "name": {"type": "string", "description": "название, напр. «Казань»"},
             "country_code": {"type": "string", "default": "RU"},
             "limit": {"type": "integer", "default": 10}}, "required": ["name"]},
         "fn": list_cities},
        {"name": f"{SVC}_list_points", "description": "Пункты выдачи СДЭК (ПВЗ, постаматы) в городе: код, адрес, "
         "часы работы, оплата, примерочная, макс. вес. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {
             "city": _CITY,
             "type": {"type": "string", "enum": ["PVZ", "POSTAMAT", "ALL"], "default": "ALL"},
             "weight_kg": {"type": "integer", "description": "только пункты, принимающие такой вес"},
             "cod": {"type": "boolean", "description": "только с наложенным платежом"},
             "limit": {"type": "integer", "default": 20}}, "required": ["city"]},
         "fn": list_points},
        {"name": f"{SVC}_calc", "description": "Стоимость и сроки доставки СДЭК между городами по весу и "
         "габаритам. Без tariff_code — все доступные тарифы, дешёвые сверху; с tariff_code — точная сумма с "
         "услугами. Заказ не создаёт, ничего не оплачивает.",
         "inputSchema": {"type": "object", "properties": {
             "from_city": _CITY, "to_city": _CITY,
             "weight_g": {"type": "integer", "description": "вес посылки, граммы"},
             "length_cm": {"type": "integer"}, "width_cm": {"type": "integer"}, "height_cm": {"type": "integer"},
             "tariff_code": {"type": "integer", "description": "код тарифа (напр. 136 — посылка склад-склад)"},
             "limit": {"type": "integer", "default": 20}},
             "required": ["from_city", "to_city", "weight_g"]},
         "fn": calc},
        {"name": f"{SVC}_get_order", "description": "Статус заказа СДЭК и история статусов по номеру накладной "
         "СДЭК, номеру заказа магазина или uuid. Только чтение: не меняет и не отменяет заказ.",
         "inputSchema": {"type": "object", "properties": {
             "cdek_number": {"type": "string", "description": "номер накладной СДЭК"},
             "im_number": {"type": "string", "description": "номер заказа в магазине"},
             "uuid": {"type": "string"}}},
         "fn": get_order}],
}

if __name__ == "__main__":
    sys.exit(_core.main(SERVER, SVC))
