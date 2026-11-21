"""МойСклад для пульта: остатки, заказы покупателей, взаиморасчёты с контрагентами — чтение; смена статуса заказа —
только черновик и подтверждение человека. Ключ — ~/.config/gastech-mcp/moysklad.token (Bearer-токен одной строкой).
Контракт — docs/CONNECTORS.md, описание — docs/connectors/moysklad.md. API — JSON API 1.2
(https://dev.moysklad.ru/doc/api/remap/1.2/, исходник документации — github.com/moysklad/api-remap-1.2-doc).

Особенности API (по документации):
- обязателен ``Accept-Encoding: gzip`` (иначе 415), ``Accept: application/json;charset=utf-8`` (иначе ошибка 1062);
- суммы и цены — в копейках, даты — ``"гггг-мм-дд чч:мм:сс"`` (время Москвы);
- лимит — 45 единиц за 3 с на пользователя; запрос по токену пользователя стоит 4 единицы (с 01.12.2026),
  отчёт об остатках ``/report/stock/all`` — 5 единиц; не больше 5 параллельных запросов;
- ``expand`` работает только при ``limit`` ≤ 100.
"""

from __future__ import annotations

import re
import sys

if __package__:
    from . import _core
else:                                                  # запуск файлом: python3 moysklad_mcp.py
    import _core

SVC = "moysklad"
DEFAULT_BASE = "https://api.moysklad.ru/api/remap/1.2"
THROTTLE = _core.Throttle(44, 3.0)                     # единицы лимита МойСклад за 3 с (запас 1 из 45)
COST = 4                                               # обычный запрос по токену пользователя
COST_STOCK = 5                                         # отчёт об остатках
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STOCK_MODES = ("all", "positiveOnly", "negativeOnly", "empty", "nonEmpty", "underMinimum")


def _api(method: str, path: str, *, cost: int = COST, **kw):
    key = _core.read_secret(SVC)
    for _ in range(cost - 1):                          # http() сам спишет последнюю единицу
        THROTTLE.wait()
    return _core.http(method, _core.base_url(SVC, DEFAULT_BASE) + path,
                      headers={"Authorization": f"Bearer {key}", "Accept-Encoding": "gzip",
                               "Accept": "application/json;charset=utf-8"},
                      keys=_core.secret_values(key), throttle=THROTTLE, service="МойСклад", **kw)


# ---------- разбор ответов ----------
def _limit(a: dict) -> int:
    return max(1, min(int(a.get("limit", 20)), 100))


def _rub(kop) -> float:
    return round(float(kop or 0) / 100, 2)


def _iso(dt: str | None) -> str | None:
    return dt.replace(" ", "T") if dt else None        # МойСклад: "2026-11-12 12:57:00" (Москва) → ISO без пояса


def _link(obj: dict) -> str | None:
    return (obj.get("meta") or {}).get("uuidHref")


def _uuid(value, what: str) -> str:
    v = str(value).strip().lower()
    if not _UUID.match(v):
        raise _core.ToolError(f"{what}: нужен id МойСклад (UUID вида 34efe2ee-015e-11e6-9464-e4de0000006b)")
    return v


def _text_filter(v: str) -> str:
    return str(v).replace(";", " ").strip()[:100]      # «;» — разделитель фильтров МойСклад


def _page(data: dict, rows: list) -> dict:
    size = int((data.get("meta") or {}).get("size") or len(rows))
    out = {"total": size, "shown": len(rows), "rows": rows}
    if size > len(rows):
        out["more"] = f"показано {len(rows)} из {size}: уточните поиск или увеличьте limit (до 100)"
    return out


def _order_row(r: dict) -> dict:
    agent, state = r.get("agent") or {}, r.get("state") or {}
    return {"id": r.get("id"), "number": r.get("name"), "date": _iso(r.get("moment")),
            "customer": agent.get("name"), "customer_id": agent.get("id"), "status": state.get("name"),
            "sum_rub": _rub(r.get("sum")), "paid_rub": _rub(r.get("payedSum")),
            "shipped_rub": _rub(r.get("shippedSum")), "delivery": _iso(r.get("deliveryPlannedMoment")),
            "comment": (r.get("description") or "")[:200], "link": _link(r)}


# ---------- инструменты: чтение ----------
def list_stock(a: dict):
    limit = _limit(a)
    mode = a.get("stock_mode") or "all"
    if mode not in STOCK_MODES:
        raise _core.ToolError(f"stock_mode: одно из {', '.join(STOCK_MODES)}")
    flt = [f"stockMode={mode}"]
    if a.get("search"):
        flt.append(f"search={_text_filter(a['search'])}")
    data = _api("GET", "/report/stock/all", cost=COST_STOCK,
                query={"limit": limit, "offset": int(a.get("offset", 0)), "filter": ";".join(flt)})
    rows = [{"id": (r.get("meta") or {}).get("href", "").split("/")[-1].split("?")[0], "name": r.get("name"),
             "code": r.get("code"), "article": r.get("article"), "stock": r.get("stock"),
             "reserve": r.get("reserve"), "available": r.get("quantity"), "in_transit": r.get("inTransit"),
             "uom": (r.get("uom") or {}).get("name"), "cost_rub": _rub(r.get("price")),
             "sale_price_rub": _rub(r.get("salePrice")), "days_in_stock": r.get("stockDays"),
             "group": (r.get("folder") or {}).get("name")} for r in data.get("rows", [])]
    return _page(data, rows)


def list_orders(a: dict):
    limit = _limit(a)
    flt = []
    if a.get("since"):
        if not _DATE.match(str(a["since"])):
            raise _core.ToolError("since: дата в виде ГГГГ-ММ-ДД")
        flt.append(f"moment>={a['since']} 00:00:00")
    q = {"limit": limit, "offset": int(a.get("offset", 0)), "order": "moment,desc", "expand": "agent,state",
         "filter": ";".join(flt) or None, "search": _text_filter(a["search"]) if a.get("search") else None}
    data = _api("GET", "/entity/customerorder", query=q)
    return _page(data, [_order_row(r) for r in data.get("rows", [])])


def get_order(a: dict):
    oid = _uuid(a.get("id", ""), "id")
    r = _api("GET", f"/entity/customerorder/{oid}", query={"expand": "agent,state,positions.assortment"})
    out = _order_row(r)
    pos = (r.get("positions") or {}).get("rows") or []
    out["positions"] = [{"name": (p.get("assortment") or {}).get("name"), "code": (p.get("assortment") or {}).get(
        "code"), "qty": p.get("quantity"), "price_rub": _rub(p.get("price")), "discount_pct": p.get("discount"),
        "sum_rub": round(_rub(p.get("price")) * float(p.get("quantity") or 0) * (1 - float(p.get("discount") or 0)
                                                                                   / 100), 2)} for p in pos[:50]]
    total = int((r.get("positions") or {}).get("meta", {}).get("size") or len(pos))
    if total > len(out["positions"]):
        out["more"] = f"показано позиций {len(out['positions'])} из {total} — полный список в МойСклад по ссылке"
    return out


def list_balances(a: dict):
    limit = _limit(a)
    q = {"limit": limit, "offset": int(a.get("offset", 0)), "filter": "balance!=0" if a.get("nonzero_only", True)
         else None}
    if a.get("search"):
        q["filter"] = ";".join(x for x in (q["filter"], f"counterparty.name~{_text_filter(a['search'])}") if x)
    data = _api("GET", "/report/counterparty", query=q)
    rows = [{"id": (r.get("counterparty") or {}).get("id"), "name": (r.get("counterparty") or {}).get("name"),
             "balance_rub": _rub(r.get("balance")), "sales_count": r.get("demandsCount"),
             "sales_rub": _rub(r.get("demandsSum")), "last_sale": _iso(r.get("lastDemandDate")),
             "link": _link(r.get("counterparty") or {})} for r in data.get("rows", [])]
    rows.sort(key=lambda x: x["balance_rub"])
    out = _page(data, rows)
    out["note"] = ("balance_rub — «Баланс» из отчёта «Показатели контрагентов». Знак (минус = долг покупателя) "
                   "по документации не описан — сверьте с карточкой контрагента. Нужна опция CRM в тарифе.")
    return out


def list_order_states(a: dict):
    data = _api("GET", "/entity/customerorder/metadata")
    kinds = {"Regular": "обычный", "Successful": "финальный: успех", "Unsuccessful": "финальный: отказ"}
    return [{"id": s.get("id"), "name": s.get("name"), "kind": kinds.get(s.get("stateType"), s.get("stateType"))}
            for s in data.get("states", [])]


# ---------- запись: черновик → человек → apply ----------
def propose_order_state(a: dict):
    oid = _uuid(a.get("id", ""), "id")
    want = str(a.get("status", "")).strip()
    if not want:
        raise _core.ToolError("status: название статуса, напр. «Подтвержден» (список — moysklad_list_order_states)")
    states = _api("GET", "/entity/customerorder/metadata").get("states", [])
    st = next((s for s in states if (s.get("name") or "").casefold() == want.casefold()), None)
    if not st:
        raise _core.ToolError(f"нет статуса «{want}»; есть: {', '.join(s.get('name', '') for s in states)}")
    order = _api("GET", f"/entity/customerorder/{oid}", query={"expand": "agent,state"})
    row = _order_row(order)
    if row["status"] == st.get("name"):
        return {"status": f"заказ {row['number']} уже в статусе «{row['status']}» — менять нечего"}
    href = (st.get("meta") or {}).get("href", "")
    params = {"order_id": oid, "state_href": href, "state_name": st.get("name")}
    return _core.propose(SVC, "set_order_state", params,
                         f"заказ №{row['number']} ({row['customer']}, {row['sum_rub']} ₽): статус «{row['status']}» → "
                         f"«{st.get('name')}»")


def apply(a: dict):
    rec = _core.take_confirmed(SVC, a.get("id", ""))
    p = rec["params"]
    if rec["action"] != "set_order_state":
        raise _core.ToolError("неизвестное действие в черновике")
    _api("PUT", f"/entity/customerorder/{_uuid(p['order_id'], 'order_id')}",
         body={"state": {"meta": {"href": p["state_href"], "type": "state", "mediaType": "application/json"}}})
    return {"done": rec["summary"]}


_LIM = {"type": "integer", "default": 20, "minimum": 1, "maximum": 100, "description": "сколько строк (до 100)"}
_OFF = {"type": "integer", "default": 0, "description": "пропустить строк (следующая страница)"}

SERVER = {
    "name": f"gas-pult-{SVC}",
    "instructions": "МойСклад: остатки, заказы покупателей, взаиморасчёты — чтение. Суммы в рублях. Смена статуса "
                    "заказа — только черновик (moysklad_propose_order_state) и подтверждение человека в пульте.",
    "keys": lambda: _core.secret_values(_core.read_secret(SVC)),
    "tools": [
        {"name": f"{SVC}_list_stock",
         "description": "Остатки товаров: остаток, резерв, доступно, ожидание, себестоимость и цена продажи в ₽, "
                        "дней на складе. Фильтры: поиск по названию, режим остатка (underMinimum — ниже "
                        "неснижаемого, для дозаказа). Ничего не меняет. Тяжёлый запрос — не чаще раза в минуту.",
         "inputSchema": {"type": "object", "properties": {
             "limit": _LIM, "offset": _OFF, "search": {"type": "string", "description": "часть названия"},
             "stock_mode": {"type": "string", "enum": list(STOCK_MODES), "default": "all"}}},
         "fn": list_stock},
        {"name": f"{SVC}_list_orders",
         "description": "Заказы покупателей, новые сверху: номер, дата, покупатель, статус, сумма/оплачено/"
                        "отгружено в ₽, ссылка. Фильтры: с даты, поиск. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {
             "limit": _LIM, "offset": _OFF, "since": {"type": "string", "description": "с даты ГГГГ-ММ-ДД"},
             "search": {"type": "string", "description": "номер, покупатель, комментарий"}}},
         "fn": list_orders},
        {"name": f"{SVC}_get_order",
         "description": "Один заказ покупателя с позициями (до 50). Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string", "description": "id заказа"}},
                         "required": ["id"]},
         "fn": get_order},
        {"name": f"{SVC}_list_balances",
         "description": "Взаиморасчёты с контрагентами (отчёт «Показатели контрагентов»): баланс в ₽, число и сумма "
                        "продаж, последняя продажа; сортировка — самый большой минус сверху. Нужна опция CRM в "
                        "тарифе МойСклад. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {
             "limit": _LIM, "offset": _OFF, "search": {"type": "string", "description": "часть названия"},
             "nonzero_only": {"type": "boolean", "default": True, "description": "только с ненулевым балансом"}}},
         "fn": list_balances},
        {"name": f"{SVC}_list_order_states",
         "description": "Статусы заказов покупателей, настроенные в аккаунте. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {}},
         "fn": list_order_states},
        {"name": f"{SVC}_propose_order_state",
         "description": "Черновик смены статуса заказа покупателя. Сам ничего не меняет: человек подтверждает в "
                        "пульте, затем moysklad_apply. Удалять заказы, менять суммы и позиции не умеет.",
         "inputSchema": {"type": "object", "properties": {
             "id": {"type": "string", "description": "id заказа"},
             "status": {"type": "string", "description": "название статуса, как в moysklad_list_order_states"}},
             "required": ["id", "status"]},
         "fn": propose_order_state},
        {"name": f"{SVC}_apply",
         "description": "Выполнить черновик, подтверждённый человеком. Без подтверждения и при GAS_MOYSKLAD_WRITE=0 "
                        "— ошибка.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
         "fn": apply}],
}

if __name__ == "__main__":
    sys.exit(_core.main(SERVER, SVC))
