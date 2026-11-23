"""amoCRM для пульта: сделки, контакты, воронки и этапы, задачи — чтение; смена этапа сделки — только через черновик
и подтверждение человека.

Ключ — JSON ``{"subdomain": "<поддомен>", "token": "<долгосрочный токен>"}`` в файле
``~/.config/gastech-mcp/amocrm.token``. Контракт — docs/CONNECTORS.md, описание — docs/connectors/amocrm.md.
API — REST v4 (``https://<поддомен>.amocrm.ru/api/v4/…``), документация: amocrm.ru/developers/content/crm_platform.
**Не проверено на песочнице** — каркас по примерам из документации.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time

if __package__:
    from . import _core
else:                                                  # запуск файлом: python3 amocrm_mcp.py
    import _core

SVC = "amocrm"
NAME = "amoCRM"
THROTTLE = _core.Throttle(7, 1.0)                      # «не более 7 запросов в секунду на одну интеграцию»
MSK = dt.timezone(dt.timedelta(hours=3))
WON, LOST = 142, 143                                   # системные этапы: успех / провал
_SUB = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ID = re.compile(r"^\d{1,12}$")
TASK_TYPE = {1: "звонок", 2: "встреча", 3: "письмо"}


def _cred() -> tuple[str, str]:
    """(поддомен, токен). Текст ошибки — без содержимого файла."""
    raw = _core.read_secret(SVC)
    try:
        d = json.loads(raw)
    except ValueError:
        d = None
    sub = str((d or {}).get("subdomain", "")).strip().lower() if isinstance(d, dict) else ""
    sub = sub.removesuffix(".amocrm.ru")
    tok = str((d or {}).get("token", "")).strip() if isinstance(d, dict) else ""
    if not _SUB.match(sub) or not tok:
        raise _core.ToolError('в файле amocrm.token должен быть JSON {"subdomain": "<поддомен>", "token": '
                              '"<долгосрочный токен>"} — см. docs/connectors/amocrm.md')
    return sub, tok


def _keys() -> list[str]:
    """Что прятать: весь файл и токен. Поддомен не прячем — он нужен в ссылках и не даёт доступа."""
    raw = _core.read_secret(SVC)
    try:
        tok = str(json.loads(raw).get("token", ""))
    except (ValueError, AttributeError):
        tok = ""
    return [raw] + ([tok] if tok else [])


def _web(sub: str) -> str:
    return f"https://{sub}.amocrm.ru"


def _api(method: str, path: str, query: dict | None = None, body=None):
    sub, tok = _cred()
    url = _core.base_url(SVC, _web(sub)) + "/api/v4" + path
    try:
        return _core.http(method, url, headers={"Authorization": f"Bearer {tok}"}, query=query, body=body,
                          keys=[tok], throttle=THROTTLE, service=NAME)
    except _core.ToolError as e:
        t = str(e)
        if " 402" in t:
            raise _core.ToolError(f"{NAME}: подписка аккаунта закончилась — API закрыт (ответ 402)") from None
        if " 403" in t:
            raise _core.ToolError(f"{NAME} ответил 403: у токена нет прав на это или аккаунт заблокирован за "
                                  "превышение лимита запросов") from None
        raise


def _iso(ts) -> str | None:
    if not ts:
        return None
    return dt.datetime.fromtimestamp(int(ts), MSK).isoformat()


def _ts(day: str, what: str) -> int:
    if not _DATE.match(str(day)):
        raise _core.ToolError(f"{what}: дата в формате ГГГГ-ММ-ДД")
    return int(dt.datetime.strptime(str(day), "%Y-%m-%d").replace(tzinfo=MSK).timestamp())


def _id(v, what: str = "id") -> int:
    if not _ID.match(str(v).strip()):
        raise _core.ToolError(f"{what}: числовой id записи amoCRM")
    return int(str(v).strip())


def _limit(a: dict) -> int:
    return max(1, min(int(a.get("limit", 20)), 100))


def _page(a: dict) -> int:
    return max(1, int(a.get("page", 1)))


def _rows(r, key: str) -> list:
    """Пустой список amoCRM отдаёт как 204 без тела — ядро вернёт {}."""
    return ((r or {}).get("_embedded") or {}).get(key) or [] if isinstance(r, dict) else []


def _more(r, page: int) -> dict:
    nxt = isinstance(r, dict) and ((r.get("_links") or {}).get("next"))
    return {"more": f"есть ещё; следующая страница — page={page + 1}"} if nxt else {}


def _money(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _cf(item: dict, code: str) -> list[str]:
    """Значения системного поля (PHONE, EMAIL) из custom_fields_values."""
    out = []
    for f in item.get("custom_fields_values") or []:
        if f.get("field_code") == code:
            out += [str(v.get("value")) for v in f.get("values") or [] if v.get("value")]
    return out


# ---------- чтение ----------
def _lead(d: dict, sub: str) -> dict:
    st = d.get("status_id")
    return {"id": d["id"], "name": d.get("name", ""), "sum": _money(d.get("price")),
            "pipeline_id": d.get("pipeline_id"), "status_id": st,
            "state": "успех" if st == WON else "провал" if st == LOST else "в работе",
            "responsible_id": d.get("responsible_user_id"), "created": _iso(d.get("created_at")),
            "updated": _iso(d.get("updated_at")), "closed": _iso(d.get("closed_at")),
            "next_task": _iso(d.get("closest_task_at")),
            "tags": [t.get("name") for t in (d.get("_embedded") or {}).get("tags") or []],
            "link": f"{_web(sub)}/leads/detail/{d['id']}"}


def list_leads(a: dict):
    q: dict = {"limit": _limit(a), "page": _page(a), "order[created_at]": "desc"}
    if a.get("pipeline_id") not in (None, ""):
        pid = _id(a["pipeline_id"], "pipeline_id")
        if a.get("status_id") not in (None, ""):
            q["filter[statuses][0][pipeline_id]"] = pid
            q["filter[statuses][0][status_id]"] = _id(a["status_id"], "status_id")
        else:
            q["filter[pipeline_id]"] = pid
    elif a.get("status_id") not in (None, ""):
        raise _core.ToolError("status_id: укажите и pipeline_id (этап в amoCRM — внутри воронки)")
    if a.get("since"):
        q["filter[created_at][from]"] = _ts(a["since"], "since")
    if a.get("search"):
        q["query"] = str(a["search"])
    sub = _cred()[0]
    r = _api("GET", "/leads", q)
    return {"page": q["page"], "rows": [_lead(d, sub) for d in _rows(r, "leads")]} | _more(r, q["page"])


def get_lead(a: dict):
    d = _api("GET", f"/leads/{_id(a.get('id', ''))}", {"with": "contacts,loss_reason"})
    if not isinstance(d, dict) or "id" not in d:
        raise _core.ToolError(f"{NAME}: сделка не найдена")
    out = _lead(d, _cred()[0])
    emb = d.get("_embedded") or {}
    out |= {"contact_ids": [c["id"] for c in emb.get("contacts") or []],
            "company_ids": [c["id"] for c in emb.get("companies") or []],
            "loss_reason": ((emb.get("loss_reason") or [{}])[0] or {}).get("name")}
    return out


def list_contacts(a: dict):
    q: dict = {"limit": _limit(a), "page": _page(a), "order[updated_at]": "desc"}
    if a.get("search"):
        q["query"] = str(a["search"])                  # имя, телефон, почта — поиск по заполненным полям
    sub = _cred()[0]
    r = _api("GET", "/contacts", q)
    rows = [{"id": c["id"], "name": c.get("name", ""), "phones": _cf(c, "PHONE"), "emails": _cf(c, "EMAIL"),
             "responsible_id": c.get("responsible_user_id"), "created": _iso(c.get("created_at")),
             "company_ids": [x["id"] for x in (c.get("_embedded") or {}).get("companies") or []],
             "link": f"{_web(sub)}/contacts/detail/{c['id']}"} for c in _rows(r, "contacts")]
    return {"page": q["page"], "rows": rows} | _more(r, q["page"])


def _pipelines() -> list[dict]:
    out = []
    for p in _rows(_api("GET", "/leads/pipelines"), "pipelines"):
        sts = sorted(_rows(p, "statuses"), key=lambda s: int(s.get("sort") or 0))
        out.append({"pipeline_id": p["id"], "name": p.get("name", ""), "main": bool(p.get("is_main")),
                    "archive": bool(p.get("is_archive")),
                    "statuses": [{"status_id": s["id"], "name": s.get("name", ""),
                                  "kind": "финальный: успех" if s["id"] == WON else
                                  "финальный: провал" if s["id"] == LOST else
                                  "неразобранное" if s.get("type") == 1 else "в работе"} for s in sts]})
    return out


def list_pipelines(a: dict):
    return {"pipelines": _pipelines()}


def list_tasks(a: dict):
    limit, page = _limit(a), _page(a)
    overdue = bool(a.get("overdue"))
    q: dict = {"limit": limit, "page": page, "order[complete_till]": "asc"}
    if overdue or a.get("open_only", True):
        q["filter[is_completed]"] = 0
    if a.get("responsible_id") not in (None, ""):
        q["filter[responsible_user_id]"] = _id(a["responsible_id"], "responsible_id")
    sub = _cred()[0]
    r = _api("GET", "/tasks", q)
    now = int(time.time())
    rows = []
    for t in _rows(r, "tasks"):
        till = int(t.get("complete_till") or 0)
        if overdue and till >= now:
            break                                     # срок по возрастанию: дальше просроченных нет
        kind = t.get("entity_type")
        rows.append({"id": t["id"], "text": (t.get("text") or "")[:300],
                     "type": TASK_TYPE.get(t.get("task_type_id"), "другое"), "deadline": _iso(till),
                     "overdue": bool(till and till < now and not t.get("is_completed")),
                     "done": bool(t.get("is_completed")), "responsible_id": t.get("responsible_user_id"),
                     "entity": f"{kind}:{t.get('entity_id')}" if kind else None,
                     "link": f"{_web(sub)}/{kind}/detail/{t['entity_id']}"
                     if kind in ("leads", "contacts", "companies") and t.get("entity_id") else None})
    more = {} if overdue and len(rows) < len(_rows(r, "tasks")) else _more(r, page)
    return {"page": page, "rows": rows} | more


# ---------- запись: черновик → человек → apply ----------
def propose_lead_status(a: dict):
    lead = _api("GET", f"/leads/{_id(a.get('id', ''))}")
    if not isinstance(lead, dict) or "id" not in lead:
        raise _core.ToolError(f"{NAME}: сделка не найдена")
    pipe = next((p for p in _pipelines() if p["pipeline_id"] == lead.get("pipeline_id")), None)
    if not pipe:
        raise _core.ToolError(f"{NAME}: не нашёл воронку сделки #{lead['id']}")
    want = str(a.get("status", "")).strip()
    hit = next((s for s in pipe["statuses"]
                if str(s["status_id"]) == want or s["name"].casefold() == want.casefold()), None)
    if not hit:
        raise _core.ToolError(f"в воронке «{pipe['name']}» нет этапа «{want}»; есть: "
                              + ", ".join(f"{s['name']} ({s['status_id']})" for s in pipe["statuses"]))
    if hit["status_id"] == lead.get("status_id"):
        return {"id": None, "status": f"сделка уже на этапе «{hit['name']}» — менять нечего"}
    cur = next((s["name"] for s in pipe["statuses"] if s["status_id"] == lead.get("status_id")),
               str(lead.get("status_id")))
    return _core.propose(SVC, "lead_status", {"lead_id": lead["id"], "pipeline_id": pipe["pipeline_id"],
                                              "status_id": hit["status_id"], "from_status_id": lead.get("status_id")},
                         f"сделка «{lead.get('name', '')}» (#{lead['id']}): «{cur}» → «{hit['name']}»")


def apply(a: dict):
    rec = _core.take_confirmed(SVC, a.get("id", ""))
    p = rec["params"]
    if rec["action"] != "lead_status":
        raise _core.ToolError("неизвестный тип черновика")
    r = _api("PATCH", f"/leads/{int(p['lead_id'])}",
             body={"pipeline_id": int(p["pipeline_id"]), "status_id": int(p["status_id"])})
    if not isinstance(r, dict) or r.get("id") != p["lead_id"]:
        raise _core.ToolError(f"{NAME} не подтвердил изменение сделки #{p['lead_id']}")
    return {"done": rec["summary"]}


_LIST = {"limit": {"type": "integer", "default": 20, "description": "сколько строк, до 100"},
         "page": {"type": "integer", "default": 1, "description": "страница (следующая — из поля more)"}}
SERVER = {
    "name": f"gas-pult-{SVC}",
    "instructions": "amoCRM: чтение сделок, контактов, воронок и этапов, задач. Запись — только смена этапа сделки: "
                    "черновик → подтверждение человека в пульте → amocrm_apply.",
    "keys": _keys,
    "tools": [
        {"name": f"{SVC}_list_leads",
         "description": "Сделки, новые сверху: название, бюджет, воронка и этап, «в работе / успех / провал», "
                        "ответственный, ближайшая задача, ссылка. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": _LIST | {
             "pipeline_id": {"type": "string", "description": "id воронки (см. amocrm_list_pipelines)"},
             "status_id": {"type": "string", "description": "id этапа; только вместе с pipeline_id"},
             "since": {"type": "string", "description": "созданы с даты ГГГГ-ММ-ДД (московское время)"},
             "search": {"type": "string", "description": "поиск по заполненным полям"}}}, "fn": list_leads},
        {"name": f"{SVC}_get_lead",
         "description": "Одна сделка подробно: плюс id контактов и компании, причина отказа. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
         "fn": get_lead},
        {"name": f"{SVC}_list_contacts",
         "description": "Контакты, недавно изменённые сверху: имя, телефоны, почта, ссылка. Поиск по имени, "
                        "телефону или почте. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": _LIST | {
             "search": {"type": "string", "description": "имя, телефон или почта"}}}, "fn": list_contacts},
        {"name": f"{SVC}_list_pipelines",
         "description": "Воронки сделок и их этапы по порядку (id и названия). Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {}}, "fn": list_pipelines},
        {"name": f"{SVC}_list_tasks",
         "description": "Задачи, ближайший срок сверху: текст, тип (звонок, встреча, письмо), срок, просрочена ли, "
                        "к какой сделке или контакту. По умолчанию невыполненные; overdue=true — только "
                        "просроченные. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": _LIST | {
             "overdue": {"type": "boolean", "default": False},
             "open_only": {"type": "boolean", "default": True},
             "responsible_id": {"type": "string"}}}, "fn": list_tasks},
        {"name": f"{SVC}_propose_lead_status",
         "description": "Черновик перевода сделки на другой этап её воронки (по id этапа или названию). Сам ничего "
                        "не меняет: человек подтверждает в пульте, затем amocrm_apply.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "status": {"type": "string"}},
                         "required": ["id", "status"]}, "fn": propose_lead_status},
        {"name": f"{SVC}_apply",
         "description": "Выполнить черновик, подтверждённый человеком (и только при GAS_AMOCRM_WRITE=1).",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
         "fn": apply}],
}

if __name__ == "__main__":
    sys.exit(_core.main(SERVER, SVC))
