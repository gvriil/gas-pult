"""YCLIENTS для пульта: записи клиентов, клиенты, сотрудники, услуги — только чтение.

Ключ — JSON ``{"partner": "<partner-токен>", "user": "<user-токен>", "company_id": "<id филиала>"}`` в файле
``~/.config/gastech-mcp/yclients.token``. Контракт — docs/CONNECTORS.md, описание — docs/connectors/yclients.md.
API — REST v2 (``https://api.yclients.com/api/v1/…``), документация: developers.yclients.com.
**Не проверено на песочнице** — каркас по документации (зеркало OpenAPI github.com/alexmaltsevgit/yclients-openapi).
Записи в сервис нет: ни создания, ни переноса, ни отмены визитов.
"""

from __future__ import annotations

import json
import re
import sys

if __package__:
    from . import _core
else:                                                  # запуск файлом: python3 yclients_mcp.py
    import _core

SVC = "yclients"
NAME = "YCLIENTS"
THROTTLE = _core.Throttle(5, 1.0)                      # консервативно; точный лимит вендора — не проверен
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID = re.compile(r"^\d{1,12}$")
ATT = {0: "ожидается", 1: "пришёл", 2: "подтвердил", -1: "не пришёл"}


def _cred() -> tuple[str, str, str]:
    raw = _core.read_secret(SVC)
    try:
        d = json.loads(raw)
    except ValueError:
        d = None
    g = (lambda k: str(d.get(k, "")).strip()) if isinstance(d, dict) else (lambda k: "")
    partner, user, cid = g("partner"), g("user"), g("company_id")
    if not partner or not user or not _ID.match(cid):
        raise _core.ToolError('в файле yclients.token должен быть JSON {"partner": "...", "user": "...", '
                              '"company_id": "<число>"} — см. docs/connectors/yclients.md')
    return partner, user, cid


def _keys() -> list[str]:
    p, u, _ = _cred()
    return [*_core.secret_values(_core.read_secret(SVC)), p, u]


def _api(method: str, path: str, query: dict | None = None, body=None):
    partner, user, cid = _cred()
    url = _core.base_url(SVC, "https://api.yclients.com/api/v1") + path.replace("{cid}", cid)
    r = _core.http(method, url, headers={"Authorization": f"Bearer {partner}, User {user}",
                                         "Accept": "application/vnd.yclients.v2+json"},
                   query=query, body=body, keys=[partner, user], throttle=THROTTLE, service=NAME)
    if isinstance(r, dict) and r.get("success") is False:
        raise _core.ToolError(f"{NAME}: {((r.get('meta') or {}).get('message')) or 'запрос отклонён'}")
    return r


def _data(r):
    return (r or {}).get("data") if isinstance(r, dict) else None


def _limit(a: dict) -> int:
    return max(1, min(int(a.get("limit", 20)), 100))


def _page(a: dict) -> int:
    return max(1, int(a.get("page", 1)))


def _id(v, what: str = "id") -> int:
    if not _ID.match(str(v).strip()):
        raise _core.ToolError(f"{what}: числовой id")
    return int(str(v).strip())


def _date(v, what: str) -> str:
    if not _DATE.match(str(v)):
        raise _core.ToolError(f"{what}: дата в формате ГГГГ-ММ-ДД")
    return str(v)


def _money(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _more(r, page: int, got: int, limit: int) -> dict:
    total = ((r or {}).get("meta") or {}).get("total_count") if isinstance(r, dict) else None
    if (total is not None and page * limit < int(total)) or (total is None and got >= limit):
        return {"more": f"возможно есть ещё; следующая страница — page={page + 1}"}
    return {}


def _record(d: dict) -> dict:
    cl = d.get("client") or {}
    return {"id": d["id"], "datetime": d.get("datetime"), "length_min": int(d.get("seance_length") or 0) // 60,
            "client_id": cl.get("id"), "client": cl.get("name", ""), "phone": cl.get("phone", ""),
            "staff_id": d.get("staff_id"), "staff": (d.get("staff") or {}).get("name", ""),
            "services": [{"title": s.get("title", ""), "cost": _money(s.get("cost"))} for s in d.get("services") or []],
            "sum": _money(sum(_money(s.get("cost")) for s in d.get("services") or [])),
            "status": ATT.get(d.get("attendance"), "неизвестно"), "deleted": bool(d.get("deleted")),
            "paid_full": bool(d.get("paid_full")), "online": bool(d.get("online")),
            "comment": (d.get("comment") or "")[:300], "created": d.get("create_date"),
            "changed": d.get("last_change_date")}


def list_records(a: dict):
    limit, page = _limit(a), _page(a)
    q: dict = {"page": page, "count": limit}
    if a.get("from"):
        q["start_date"] = _date(a["from"], "from")
    if a.get("to"):
        q["end_date"] = _date(a["to"], "to")
    for k, p in (("staff_id", "staff_id"), ("client_id", "client_id")):
        if a.get(k) not in (None, ""):
            q[p] = _id(a[k], k)
    r = _api("GET", "/records/{cid}", q)
    rows = [_record(d) for d in _data(r) or [] if isinstance(d, dict) and "id" in d]
    return {"page": page, "rows": rows} | _more(r, page, len(rows), limit)


def get_record(a: dict):
    d = _data(_api("GET", f"/record/{{cid}}/{_id(a.get('id', ''))}"))
    if not isinstance(d, dict) or "id" not in d:
        raise _core.ToolError(f"{NAME}: запись не найдена")
    return _record(d)


def list_clients(a: dict):
    limit, page = _limit(a), _page(a)
    body: dict = {"page": page, "page_size": limit}
    if a.get("search"):
        body["filters"] = [{"type": "quick_search", "state": {"value": str(a["search"])}}]
    r = _api("POST", "/company/{cid}/clients/search", body=body)       # POST, но только чтение
    rows = [{"id": c["id"], "name": c.get("name", ""), "phone": c.get("phone", ""), "email": c.get("email", ""),
             "visits": int(c.get("visits") or 0), "spent": _money(c.get("spent")), "balance": _money(c.get("balance")),
             "last_change": c.get("last_change_date")} for c in _data(r) or [] if isinstance(c, dict) and "id" in c]
    return {"page": page, "rows": rows} | _more(r, page, len(rows), limit)


def list_staff(a: dict):
    rows = [{"id": s["id"], "name": s.get("name", ""), "position": (s.get("position") or {}).get("title")
             or s.get("specialization", ""), "active": not s.get("fired") and not s.get("hidden"),
             "rating": s.get("rating")} for s in _data(_api("GET", "/company/{cid}/staff")) or []
            if isinstance(s, dict) and "id" in s]
    return {"rows": rows}


def list_services(a: dict):
    rows = [{"id": s["id"], "title": s.get("title", ""), "price_min": _money(s.get("price_min")),
             "price_max": _money(s.get("price_max")), "duration_min": int(s.get("duration") or 0) // 60,
             "active": bool(s.get("active", 1))} for s in _data(_api("GET", "/company/{cid}/services")) or []
            if isinstance(s, dict) and "id" in s]
    return {"rows": rows}


_LIST = {"limit": {"type": "integer", "default": 20, "description": "сколько строк, до 100"},
         "page": {"type": "integer", "default": 1, "description": "страница (следующая — из поля more)"}}
SERVER = {
    "name": f"gas-pult-{SVC}",
    "instructions": "YCLIENTS: только чтение записей, клиентов, сотрудников и услуг. Ничего не создаёт и не меняет.",
    "keys": _keys,
    "tools": [
        {"name": f"{SVC}_list_records",
         "description": "Записи (визиты): время, клиент и телефон, мастер, услуги и сумма, статус (ожидается / "
                        "пришёл / подтвердил / не пришёл), оплачена ли. Фильтры: период, мастер, клиент. "
                        "Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": _LIST | {
             "from": {"type": "string", "description": "с даты ГГГГ-ММ-ДД"},
             "to": {"type": "string", "description": "по дату ГГГГ-ММ-ДД"},
             "staff_id": {"type": "string"}, "client_id": {"type": "string"}}}, "fn": list_records},
        {"name": f"{SVC}_get_record",
         "description": "Одна запись подробно (те же поля). Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
         "fn": get_record},
        {"name": f"{SVC}_list_clients",
         "description": "Клиенты: имя, телефон, почта, число визитов, потрачено, баланс. Поиск по имени или "
                        "телефону. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": _LIST | {
             "search": {"type": "string", "description": "имя или телефон"}}}, "fn": list_clients},
        {"name": f"{SVC}_list_staff",
         "description": "Сотрудники филиала: имя, должность, работает ли, рейтинг. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {}}, "fn": list_staff},
        {"name": f"{SVC}_list_services",
         "description": "Услуги филиала: название, цена от и до, длительность, активна ли. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {}}, "fn": list_services}],
}

if __name__ == "__main__":
    sys.exit(_core.main(SERVER, SVC))
