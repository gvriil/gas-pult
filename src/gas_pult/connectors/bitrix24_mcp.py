"""Битрикс24 для пульта: сделки, лиды, контакты, стадии воронки, задачи — чтение; смена стадии сделки — только через
черновик и подтверждение человека.

Ключ — адрес входящего вебхука целиком (``https://<портал>/rest/<id пользователя>/<код>/``) в файле
``~/.config/gastech-mcp/bitrix24.token``. Контракт — docs/CONNECTORS.md, описание — docs/connectors/bitrix24.md.
Методы — классический REST (``crm.deal.list`` и т. п.), документация: github.com/bitrix24/b24restdocs.
**Не проверено на песочнице** — каркас по примерам из документации.
"""

from __future__ import annotations

import re
import sys

if __package__:
    from . import _core
else:                                                  # запуск файлом: python3 bitrix24_mcp.py
    import _core

SVC = "bitrix24"
NAME = "Битрикс24"
PAGE = 50                                              # размер страницы *.list у Битрикс24 — всегда 50
THROTTLE = _core.Throttle(2, 1.0)                      # «2 запроса в секунду» — тарифы кроме Enterprise (limits.md)
_HOOK = re.compile(r"^https://([A-Za-z0-9.-]+)/rest/(\d+)/([A-Za-z0-9_]+)/?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID = re.compile(r"^\d{1,12}$")
SEMANTICS = {"process": "в работе", "success": "финальный: успех", "failure": "финальный: провал",
             "apology": "финальный: провал"}
TASK_STATUS = {"2": "ждёт выполнения", "3": "выполняется", "4": "ждёт контроля", "5": "завершена",
               "6": "отложена", "7": "отклонена"}
READ = {"crm.deal.list", "crm.deal.get", "crm.lead.list", "crm.contact.list", "crm.status.list", "tasks.task.list"}


def _hook() -> tuple[str, str, str, str]:
    """(весь вебхук, хост портала, id пользователя, код). Текст ошибки — без содержимого файла."""
    raw = _core.read_secret(SVC)
    m = _HOOK.match(raw)
    if not m:
        raise _core.ToolError("в файле bitrix24.token должен быть адрес входящего вебхука "
                              "https://<портал>/rest/<id пользователя>/<код>/ — см. docs/connectors/bitrix24.md")
    return raw, m.group(1), m.group(2), m.group(3)


def _keys() -> list[str]:
    """Что прятать в ответах: весь вебхук (со слешем и без) и отдельно секретный код."""
    raw = _core.read_secret(SVC)
    m = _HOOK.match(raw)
    return [raw, raw.rstrip("/")] + ([m.group(3)] if m else [])


def _call(method: str, params: dict | None = None):
    """Один вызов REST: POST JSON на <портал>/rest/<user>/<код>/<метод>.json. Ошибки Битрикс24 — понятным текстом."""
    raw, host, user, code = _hook()
    url = f"{_core.base_url(SVC, 'https://' + host)}/rest/{user}/{code}/{method}.json"
    try:
        r = _core.http("POST", url, body=params or {}, keys=[raw, raw.rstrip("/"), code], throttle=THROTTLE,
                       service=NAME)
    except _core.ToolError as e:
        t = str(e)
        if "QUERY_LIMIT_EXCEEDED" in t or "OPERATION_TIME_LIMIT" in t:
            raise _core.ToolError(f"{NAME}: лимит запросов портала (2 в секунду) — подождите несколько секунд") \
                from None
        if "REST is available only" in t:
            raise _core.ToolError(f"{NAME}: на тарифе портала REST API недоступен (нужен тариф с REST или "
                                  "подписка Маркетплейса)") from None
        if "insufficient_scope" in t:
            raise _core.ToolError(f"{NAME}: у вебхука нет прав на {method.split('.')[0]} — добавьте право в "
                                  "настройках вебхука") from None
        raise
    if isinstance(r, dict) and r.get("error"):
        raise _core.ToolError(_core.hide(f"{NAME}: {r.get('error_description') or r['error']}", raw, code))
    if not isinstance(r, dict) or "result" not in r:
        raise _core.ToolError(f"{NAME}: неожиданный ответ на {method}")
    return r


def _host() -> str:
    return _hook()[1]


def _limit(a: dict) -> int:
    return max(1, min(int(a.get("limit", 20)), 100))


def _offset(a: dict) -> int:
    return max(0, int(a.get("offset", 0)))


def _since(a: dict, key: str = "since") -> str | None:
    v = a.get(key)
    if v in (None, ""):
        return None
    if not _DATE.match(str(v)):
        raise _core.ToolError(f"{key}: дата в формате ГГГГ-ММ-ДД")
    return str(v)


def _id(v, what: str = "id") -> str:
    if not _ID.match(str(v).strip()):
        raise _core.ToolError(f"{what}: числовой id записи Битрикс24")
    return str(v).strip()


def _money(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _pages(method: str, params: dict, limit: int, offset: int, rows=lambda r: r["result"]) -> dict:
    """Список до ``limit`` строк начиная с ``offset``: страницы по 50 (``start``), не больше двух запросов."""
    out, total, start = [], None, offset
    while len(out) < limit:
        r = _call(method, params | {"start": start})
        got = rows(r) or []
        total = r.get("total", total)
        out += got[: limit - len(out)]
        if "next" not in r or not got:
            break
        start = int(r["next"])
    res = {"total": total, "rows": out}
    if total is not None and offset + len(out) < int(total):
        res["more"] = f"показано {len(out)} из {total}; следующая страница — offset={offset + len(out)}"
    return res


# ---------- чтение ----------
DEAL_FIELDS = ["ID", "TITLE", "STAGE_ID", "CATEGORY_ID", "OPPORTUNITY", "CURRENCY_ID", "CONTACT_ID", "COMPANY_ID",
               "ASSIGNED_BY_ID", "DATE_CREATE", "CLOSEDATE", "CLOSED", "STAGE_SEMANTIC_ID"]


def _deal(d: dict, host: str) -> dict:
    return {"id": d["ID"], "title": d.get("TITLE", ""), "stage_id": d.get("STAGE_ID", ""),
            "category_id": d.get("CATEGORY_ID") or "0", "sum": _money(d.get("OPPORTUNITY")),
            "currency": d.get("CURRENCY_ID") or "RUB", "contact_id": d.get("CONTACT_ID"),
            "company_id": d.get("COMPANY_ID"), "responsible_id": d.get("ASSIGNED_BY_ID"),
            "created": d.get("DATE_CREATE"), "close_date": d.get("CLOSEDATE"), "closed": d.get("CLOSED") == "Y",
            "link": f"https://{host}/crm/deal/details/{d['ID']}/"}


def list_deals(a: dict):
    f: dict = {}
    if a.get("open_only", True):
        f["CLOSED"] = "N"
    if a.get("stage"):
        f["STAGE_ID"] = str(a["stage"])
    if a.get("category") not in (None, ""):
        f["CATEGORY_ID"] = _id(a["category"], "category")
    if since := _since(a):
        f[">=DATE_CREATE"] = since
    if a.get("search"):
        f["%TITLE"] = str(a["search"])
    host = _host()
    res = _pages("crm.deal.list", {"filter": f, "order": {"DATE_CREATE": "DESC"}, "select": DEAL_FIELDS},
                 _limit(a), _offset(a))
    res["rows"] = [_deal(d, host) for d in res["rows"]]
    return res


def get_deal(a: dict):
    d = _call("crm.deal.get", {"id": _id(a.get("id", ""))})["result"]
    out = _deal(d, _host())
    out |= {"probability": d.get("PROBABILITY"), "source": d.get("SOURCE_ID"),
            "comments": (d.get("COMMENTS") or "")[:1000], "modified": d.get("DATE_MODIFY"),
            "stage_kind": {"P": "в работе", "S": "успех", "F": "провал"}.get(d.get("STAGE_SEMANTIC_ID") or "", "")}
    return out


def list_leads(a: dict):
    f: dict = {}
    if a.get("status"):
        f["STATUS_ID"] = str(a["status"])
    if since := _since(a):
        f[">=DATE_CREATE"] = since
    if a.get("search"):
        f["%TITLE"] = str(a["search"])
    host = _host()
    res = _pages("crm.lead.list", {"filter": f, "order": {"DATE_CREATE": "DESC"},
                                   "select": ["ID", "TITLE", "NAME", "LAST_NAME", "STATUS_ID", "SOURCE_ID",
                                              "OPPORTUNITY", "CURRENCY_ID", "ASSIGNED_BY_ID", "DATE_CREATE",
                                              "HAS_PHONE", "HAS_EMAIL", "COMMENTS"]}, _limit(a), _offset(a))
    res["rows"] = [{"id": d["ID"], "title": d.get("TITLE", ""),
                    "name": " ".join(x for x in (d.get("NAME"), d.get("LAST_NAME")) if x),
                    "status_id": d.get("STATUS_ID"), "source": d.get("SOURCE_ID"),
                    "sum": _money(d.get("OPPORTUNITY")), "currency": d.get("CURRENCY_ID") or "RUB",
                    "has_phone": d.get("HAS_PHONE") == "Y", "has_email": d.get("HAS_EMAIL") == "Y",
                    "responsible_id": d.get("ASSIGNED_BY_ID"), "created": d.get("DATE_CREATE"),
                    "comments": (d.get("COMMENTS") or "")[:300],
                    "link": f"https://{host}/crm/lead/details/{d['ID']}/"} for d in res["rows"]]
    return res


def list_contacts(a: dict):
    f: dict = {}
    if a.get("phone"):
        f["PHONE"] = str(a["phone"])                    # множественное поле: только точное совпадение (документация)
    if a.get("search"):
        f["%LAST_NAME"] = str(a["search"])
    host = _host()
    res = _pages("crm.contact.list", {"filter": f, "order": {"DATE_CREATE": "DESC"},
                                      "select": ["ID", "NAME", "LAST_NAME", "PHONE", "EMAIL", "COMPANY_ID",
                                                 "ASSIGNED_BY_ID", "DATE_CREATE"]}, _limit(a), _offset(a))
    res["rows"] = [{"id": d["ID"], "name": " ".join(x for x in (d.get("NAME"), d.get("LAST_NAME")) if x),
                    "phones": [p.get("VALUE") for p in d.get("PHONE") or []],
                    "emails": [p.get("VALUE") for p in d.get("EMAIL") or []],
                    "company_id": d.get("COMPANY_ID"), "responsible_id": d.get("ASSIGNED_BY_ID"),
                    "created": d.get("DATE_CREATE"),
                    "link": f"https://{host}/crm/contact/details/{d['ID']}/"} for d in res["rows"]]
    return res


def _stages(category: str) -> list[dict]:
    entity = "DEAL_STAGE" if category in ("", "0") else f"DEAL_STAGE_{category}"
    rows = _call("crm.status.list", {"filter": {"ENTITY_ID": entity}, "order": {"SORT": "ASC"}})["result"]
    return [{"stage_id": s["STATUS_ID"], "name": s.get("NAME", ""),
             "kind": SEMANTICS.get((s.get("EXTRA") or {}).get("SEMANTICS") or "process", "в работе")}
            for s in sorted(rows, key=lambda s: int(s.get("SORT") or 0))]


def list_stages(a: dict):
    cat = _id(a["category"], "category") if a.get("category") not in (None, "") else "0"
    return {"category_id": cat, "stages": _stages(cat)}


def list_tasks(a: dict):
    f: dict = {}
    if a.get("overdue"):
        f["STATUS"] = -1                                # мета-статус «просрочена» (документация tasks.task.list)
    elif a.get("open_only", True):
        f["<REAL_STATUS"] = 5                           # 2 ждёт, 3 выполняется, 4 ждёт контроля
    if a.get("responsible_id") not in (None, ""):
        f["RESPONSIBLE_ID"] = _id(a["responsible_id"], "responsible_id")
    if a.get("search"):
        f["%TITLE"] = str(a["search"])
    host = _host()
    res = _pages("tasks.task.list", {"filter": f, "order": {"DEADLINE": "ASC"},
                                     "select": ["ID", "TITLE", "STATUS", "DEADLINE", "CREATED_DATE",
                                                "RESPONSIBLE_ID", "PRIORITY", "UF_CRM_TASK"]},
                 _limit(a), _offset(a), rows=lambda r: (r["result"] or {}).get("tasks", []))
    res["rows"] = [{"id": t["id"], "title": t.get("title", ""),
                    "status": TASK_STATUS.get(str(t.get("status")), str(t.get("status"))),
                    "deadline": t.get("deadline"), "created": t.get("createdDate"),
                    "responsible": (t.get("responsible") or {}).get("name") or t.get("responsibleId"),
                    "high_priority": str(t.get("priority")) == "2", "crm": t.get("ufCrmTask") or [],
                    "link": f"https://{host}/company/personal/user/0/tasks/task/view/{t['id']}/"}
                   for t in res["rows"]]
    return res


# ---------- запись: черновик → человек → apply ----------
def propose_deal_stage(a: dict):
    deal = _call("crm.deal.get", {"id": _id(a.get("id", ""))})["result"]
    cat = str(deal.get("CATEGORY_ID") or "0")
    stages = _stages(cat)
    want = str(a.get("stage", "")).strip()
    hit = next((s for s in stages if s["stage_id"] == want or s["name"].casefold() == want.casefold()), None)
    if not hit:
        raise _core.ToolError(f"в воронке сделки нет стадии «{want}»; есть: "
                              + ", ".join(f"{s['name']} ({s['stage_id']})" for s in stages))
    cur = next((s["name"] for s in stages if s["stage_id"] == deal.get("STAGE_ID")), deal.get("STAGE_ID"))
    if hit["stage_id"] == deal.get("STAGE_ID"):
        return {"id": None, "status": f"сделка уже на стадии «{hit['name']}» — менять нечего"}
    return _core.propose(SVC, "deal_stage", {"deal_id": deal["ID"], "stage_id": hit["stage_id"],
                                             "from_stage_id": deal.get("STAGE_ID")},
                         f"сделка «{deal.get('TITLE', '')}» (#{deal['ID']}): «{cur}» → «{hit['name']}»")


def apply(a: dict):
    rec = _core.take_confirmed(SVC, a.get("id", ""))
    p = rec["params"]
    if rec["action"] != "deal_stage":
        raise _core.ToolError("неизвестный тип черновика")
    r = _call("crm.deal.update", {"id": p["deal_id"], "fields": {"STAGE_ID": p["stage_id"]}})
    if r.get("result") is not True:
        raise _core.ToolError(f"{NAME} не подтвердил изменение сделки #{p['deal_id']}")
    return {"done": rec["summary"]}


_LIST = {"limit": {"type": "integer", "default": 20, "description": "сколько строк, до 100"},
         "offset": {"type": "integer", "default": 0, "description": "пропустить строк (следующая страница)"}}
SERVER = {
    "name": f"gas-pult-{SVC}",
    "instructions": "Битрикс24 (CRM и задачи): чтение сделок, лидов, контактов, стадий, задач. Запись — только смена "
                    "стадии сделки: черновик → подтверждение человека в пульте → bitrix24_apply.",
    "keys": _keys,
    "tools": [
        {"name": f"{SVC}_list_deals",
         "description": "Сделки, новые сверху: название, стадия, сумма, ответственный, ссылка. По умолчанию только "
                        "открытые. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": _LIST | {
             "stage": {"type": "string", "description": "STAGE_ID, напр. NEW или C1:NEW (см. bitrix24_list_stages)"},
             "category": {"type": "string", "description": "id воронки, 0 — основная"},
             "since": {"type": "string", "description": "созданы с даты ГГГГ-ММ-ДД"},
             "search": {"type": "string", "description": "часть названия"},
             "open_only": {"type": "boolean", "default": True}}}, "fn": list_deals},
        {"name": f"{SVC}_get_deal", "description": "Одна сделка подробно (комментарий, вероятность, источник). "
                                                  "Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
         "fn": get_deal},
        {"name": f"{SVC}_list_leads",
         "description": "Лиды (заявки), новые сверху: имя, статус, источник, есть ли телефон/почта, ссылка. "
                        "Телефоны не отдаёт — для них bitrix24_list_contacts. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": _LIST | {
             "status": {"type": "string", "description": "STATUS_ID, напр. NEW, IN_PROCESS"},
             "since": {"type": "string", "description": "созданы с даты ГГГГ-ММ-ДД"},
             "search": {"type": "string", "description": "часть названия"}}}, "fn": list_leads},
        {"name": f"{SVC}_list_contacts",
         "description": "Контакты: имя, телефоны, почта, ссылка. Поиск по фамилии или точному телефону. "
                        "Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": _LIST | {
             "search": {"type": "string", "description": "часть фамилии"},
             "phone": {"type": "string", "description": "телефон точно как в CRM"}}}, "fn": list_contacts},
        {"name": f"{SVC}_list_stages", "description": "Стадии воронки сделок по порядку. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {
             "category": {"type": "string", "description": "id воронки, 0 — основная"}}}, "fn": list_stages},
        {"name": f"{SVC}_list_tasks",
         "description": "Задачи, ближайший срок сверху: статус, срок, ответственный, ссылка. По умолчанию открытые; "
                        "overdue=true — только просроченные. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": _LIST | {
             "overdue": {"type": "boolean", "default": False},
             "open_only": {"type": "boolean", "default": True},
             "responsible_id": {"type": "string"},
             "search": {"type": "string", "description": "часть названия"}}}, "fn": list_tasks},
        {"name": f"{SVC}_propose_deal_stage",
         "description": "Черновик перевода сделки на другую стадию (по STAGE_ID или названию). Сам ничего не "
                        "меняет: человек подтверждает в пульте, затем bitrix24_apply.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "stage": {"type": "string"}},
                         "required": ["id", "stage"]}, "fn": propose_deal_stage},
        {"name": f"{SVC}_apply",
         "description": "Выполнить черновик, подтверждённый человеком (и только при GAS_BITRIX24_WRITE=1).",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
         "fn": apply}],
}

if __name__ == "__main__":
    sys.exit(_core.main(SERVER, SVC))
