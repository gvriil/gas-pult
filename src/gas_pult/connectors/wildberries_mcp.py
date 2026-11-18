"""Wildberries для пульта: отзывы и вопросы покупателей, цены и скидки, заказы — чтение. Запись — только ответ на
отзыв или вопрос: черновик → «Да» человека → отправка. Цены, акции, поставки, карточки не меняем.

Ключ — токен WB API одной строкой в ``~/.config/gastech-mcp/wildberries.token`` (путь — ``GAS_WILDBERRIES_KEY_FILE``).
Среда: тестовый токен (песочница) или боевой определяется по полю ``t`` в токене (JWT, документация WB «Как устроен
токен»); переопределить — ``GAS_WILDBERRIES_ENV=sandbox|prod``. ``GAS_WILDBERRIES_BASE`` — один адрес для всех
категорий (тесты). Контракт — docs/CONNECTORS.md, описание — docs/connectors/wildberries.md.
Документация: https://dev.wildberries.ru/openapi/api-information (OpenAPI: /api/swagger/yaml/ru/09-communications.yaml,
02-items.yaml, 12-reports.yaml — скачаны 18.11.2026). **Не проверено на песочнице** — ключа ещё нет.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

if __package__:
    from . import _core
else:                                                  # запуск файлом: python3 wildberries_mcp.py
    import _core

SVC = "wildberries"
NAME = "Wildberries"
# Категории WB API: свой домен у каждой. Песочницы для «Статистики» у WB нет (01-general.yaml, список серверов).
HOSTS = {"feedbacks": "feedbacks-api", "prices": "discounts-prices-api", "statistics": "statistics-api"}
SANDBOX_HOSTS = {"feedbacks", "prices"}
# Лимиты из документации: песочница — 1 запрос/с на категорию; бой — отзывы 3/с, цены 10 за 6 с,
# статистика 1 в минуту (всплеск 10) — её не душим у себя, WB ответит 429, ядро переведёт в понятную ошибку.
THROTTLE = {"feedbacks": _core.Throttle(1, 1.0), "prices": _core.Throttle(1, 1.0), "statistics": None}
MSK = timezone(timedelta(hours=3))
_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _env(key: str) -> str:
    """sandbox | prod: явная настройка, иначе поле ``t`` из полезной нагрузки токена (у тестового токена t=true)."""
    forced = os.environ.get("GAS_WILDBERRIES_ENV", "").strip().lower()
    if forced in ("sandbox", "prod"):
        return forced
    try:
        part = key.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return "sandbox" if payload.get("t") is True else "prod"
    except (IndexError, ValueError, AttributeError):
        return "sandbox"                               # не JWT — безопасный вариант: песочница


def _base(category: str, env: str) -> str:
    override = os.environ.get("GAS_WILDBERRIES_BASE")
    if override:
        return override.rstrip("/")
    if env == "sandbox":
        if category not in SANDBOX_HOSTS:
            raise _core.ToolError("у Wildberries нет песочницы для статистики (заказы): нужен боевой токен "
                                  "«только чтение» с категорией «Статистика», см. docs/connectors/wildberries.md")
        return f"https://{HOSTS[category]}-sandbox.wildberries.ru"
    return f"https://{HOSTS[category]}.wildberries.ru"


def _api(category: str, method: str, path: str, **kw):
    key = _core.read_secret(SVC)
    env = _env(key)
    data = _core.http(method, _base(category, env) + path, headers={"Authorization": key},
                      keys=_core.secret_values(key), throttle=THROTTLE[category], service=NAME, **kw)
    if isinstance(data, dict) and data.get("error") is True:
        raise _core.ToolError(f"{NAME}: {data.get('errorText') or 'ошибка без описания'}")
    return data, env


def _note(env: str) -> str:
    return "песочница WB: данные тестовые" if env == "sandbox" else "боевой кабинет WB"


def _limit(a: dict, default: int = 20) -> int:
    return max(1, min(int(a.get("limit", default)), 100))


def _skip(a: dict) -> int:
    return max(0, min(int(a.get("skip", 0)), 199990))


def _nm(a: dict) -> int | None:
    v = a.get("nm_id")
    return None if v in (None, "") else int(v)


def _answered(a: dict) -> str:
    return "true" if a.get("answered") is True or str(a.get("answered")).lower() == "true" else "false"


def _day(s: str, what: str) -> datetime:
    if not _DATE.match(str(s)):
        raise _core.ToolError(f"{what}: дата в виде ГГГГ-ММ-ДД")
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=MSK)


def _product_link(nm: int | None) -> str | None:
    # Формат ссылки — с сайта WB, не из документации API.
    return f"https://www.wildberries.ru/catalog/{nm}/detail.aspx" if nm else None


def _product(d: dict) -> dict:
    p = d.get("productDetails") or {}
    return {"nm_id": p.get("nmId"), "article": p.get("supplierArticle"), "product": p.get("productName"),
            "brand": p.get("brandName"), "link": _product_link(p.get("nmId"))}


def _answer_text(d: dict) -> str | None:
    ans = d.get("answer")
    return ans.get("text") if isinstance(ans, dict) else None


def _comm_query(a: dict, limit: int) -> dict:
    q = {"isAnswered": _answered(a), "take": limit, "skip": _skip(a), "order": "dateDesc", "nmId": _nm(a)}
    if a.get("date_from"):
        q["dateFrom"] = int(_day(a["date_from"], "date_from").timestamp())
    return q


# ---------- чтение ----------
def list_feedbacks(a: dict):
    limit = _limit(a)
    data, env = _api("feedbacks", "GET", "/api/v1/feedbacks", query=_comm_query(a, limit))
    d = data.get("data") or {}
    rows = []
    for f in d.get("feedbacks") or []:
        text = " ".join(x for x in (f.get("text"), f.get("pros") and f"Плюсы: {f['pros']}",
                                    f.get("cons") and f"Минусы: {f['cons']}") if x)
        rows.append({"id": f.get("id"), "date": f.get("createdDate"), "rating": f.get("productValuation"),
                     "text": text[:1000], "photos": len(f.get("photoLinks") or []), "video": bool(f.get("video")),
                     **_product(f), "size": (f.get("productDetails") or {}).get("size"),
                     "answer": _answer_text(f)})
    out = {"среда": _note(env), "unanswered_total": d.get("countUnanswered"),
           "answered_total": d.get("countArchive"), "rows": rows}
    if len(rows) == limit:
        out["more"] = f"показано {limit}; следующие — skip={_skip(a) + limit}"
    return out


def list_questions(a: dict):
    limit = _limit(a)
    data, env = _api("feedbacks", "GET", "/api/v1/questions", query=_comm_query(a, limit))
    d = data.get("data") or {}
    rows = [{"id": x.get("id"), "date": x.get("createdDate"), "text": (x.get("text") or "")[:1000], **_product(x),
             "answer": _answer_text(x), "viewed": x.get("wasViewed")} for x in d.get("questions") or []]
    out = {"среда": _note(env), "unanswered_total": d.get("countUnanswered"),
           "answered_total": d.get("countArchive"), "rows": rows}
    if len(rows) == limit:
        out["more"] = f"показано {limit}; следующие — skip={_skip(a) + limit}"
    return out


def list_prices(a: dict):
    limit, offset = _limit(a), max(0, int(a.get("offset", 0)))
    data, env = _api("prices", "GET", "/api/v2/list/goods/filter",
                     query={"limit": limit, "offset": offset, "filterNmID": _nm(a)})
    rows = []
    for g in (data.get("data") or {}).get("listGoods") or []:
        sizes = g.get("sizes") or []
        first = sizes[0] if sizes else {}
        row = {"nm_id": g.get("nmID"), "article": g.get("vendorCode"), "currency": g.get("currencyIsoCode4217"),
               "price": first.get("price"), "discount_pct": g.get("discount"),
               "price_with_discount": first.get("discountedPrice"), "club_discount_pct": g.get("clubDiscount"),
               "club_price": first.get("clubDiscountedPrice"), "link": _product_link(g.get("nmID"))}
        if len({s.get("price") for s in sizes}) > 1:  # разные цены по размерам — показать все
            row["sizes"] = [{"size": s.get("techSizeName"), "price": s.get("price"),
                             "price_with_discount": s.get("discountedPrice")} for s in sizes[:20]]
        rows.append(row)
    out = {"среда": _note(env), "rows": rows}
    if len(rows) == limit:
        out["more"] = f"показано {limit}; следующие — offset={offset + limit}"
    return out


def list_orders(a: dict):
    limit = _limit(a)
    since = _day(a["date_from"], "date_from") if a.get("date_from") else \
        datetime.now(MSK).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    data, env = _api("statistics", "GET", "/api/v1/supplier/orders",
                     query={"dateFrom": since.strftime("%Y-%m-%dT%H:%M:%S"), "flag": 0})
    items = data if isinstance(data, list) else []
    items.sort(key=lambda o: o.get("date") or "", reverse=True)
    rows = [{"date": o.get("date"), "srid": o.get("srid"), "nm_id": o.get("nmId"), "article": o.get("supplierArticle"),
             "product": o.get("subject"), "brand": o.get("brand"), "size": o.get("techSize"),
             "warehouse": o.get("warehouseName"), "region": o.get("regionName"),
             "price_with_discount": o.get("priceWithDisc"), "buyer_paid": o.get("finishedPrice"),
             "cancelled": bool(o.get("isCancel"))} for o in items[:limit]]
    live = [o for o in items if not o.get("isCancel")]
    out = {"среда": _note(env), "since_msk": since.strftime("%Y-%m-%dT%H:%M:%S"),
           "total": len(items), "cancelled": len(items) - len(live),
           "sum_price_with_discount": round(sum(float(o.get("priceWithDisc") or 0) for o in live), 2),
           "note": "1 строка = 1 единица товара; данные WB предварительные, обновляются раз в 30 мин",
           "rows": rows}
    if len(items) > limit:
        out["more"] = f"показано {limit} из {len(items)} (свежие сверху); итоги — по всем"
    return out


# ---------- запись: только ответ покупателю, через подтверждение ----------
def _check(a: dict) -> tuple[str, str]:
    pid, text = str(a.get("id", "")).strip(), str(a.get("text", "")).strip()
    if not _ID.match(pid):
        raise _core.ToolError("id — идентификатор отзыва/вопроса из list_feedbacks/list_questions")
    if not 2 <= len(text) <= 5000:
        raise _core.ToolError("текст ответа — от 2 до 5000 символов")
    return pid, text


def propose_feedback_answer(a: dict):
    fid, text = _check(a)
    return _core.propose(SVC, "feedback_answer", {"id": fid, "text": text},
                         f"Ответ на отзыв {fid} на Wildberries (увидят все покупатели): «{text[:300]}»")


def propose_question_answer(a: dict):
    qid, text = _check(a)
    return _core.propose(SVC, "question_answer", {"id": qid, "text": text},
                         f"Ответ на вопрос {qid} на Wildberries (увидят все покупатели): «{text[:300]}»")


def apply(a: dict):
    rec = _core.take_confirmed(SVC, a.get("id", ""))
    p = rec["params"]
    if rec["action"] == "feedback_answer":
        _api("feedbacks", "POST", "/api/v1/feedbacks/answer", body={"id": p["id"], "text": p["text"]})
    elif rec["action"] == "question_answer":
        _api("feedbacks", "PATCH", "/api/v1/questions",
             body={"id": p["id"], "answer": {"text": p["text"]}, "state": "wbRu"})
    else:
        raise _core.ToolError(f"неизвестное действие черновика: {rec['action']}")
    return {"done": rec["summary"], "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


_LIST = {"limit": {"type": "integer", "default": 20, "description": "сколько строк, 1–100"}}
_COMM = {**_LIST,
         "answered": {"type": "boolean", "default": False, "description": "true — обработанные, false — ждут ответа"},
         "nm_id": {"type": "integer", "description": "артикул WB (необязательно)"},
         "skip": {"type": "integer", "default": 0},
         "date_from": {"type": "string", "description": "с какой даты, ГГГГ-ММ-ДД (необязательно)"}}
_ANSWER = {"type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
           "required": ["id", "text"]}

SERVER = {
    "name": f"gas-pult-{SVC}",
    "instructions": "Wildberries: отзывы, вопросы, цены, заказы — чтение. Ответ покупателю — только черновик, "
                    "публикует человек после «Да». Цены, акции, поставки, карточки не меняет.",
    "keys": lambda: _core.secret_values(_core.read_secret(SVC)),
    "tools": [
        {"name": f"{SVC}_list_feedbacks",
         "description": "Отзывы покупателей WB: оценка, текст, товар, ответ продавца; по умолчанию — ждущие ответа, "
                        "свежие сверху. Имя покупателя не отдаёт. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": _COMM}, "fn": list_feedbacks},
        {"name": f"{SVC}_list_questions",
         "description": "Вопросы покупателей WB о товарах; по умолчанию — без ответа, свежие сверху. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": _COMM}, "fn": list_questions},
        {"name": f"{SVC}_list_prices",
         "description": "Цены и скидки товаров WB: цена, скидка продавца, цена со скидкой, цена с WB Клубом. "
                        "Цены не меняет.",
         "inputSchema": {"type": "object", "properties": {
             **_LIST, "offset": {"type": "integer", "default": 0},
             "nm_id": {"type": "integer", "description": "один артикул WB (необязательно)"}}}, "fn": list_prices},
        {"name": f"{SVC}_list_orders",
         "description": "Заказы WB с даты (по умолчанию со вчера, время Москвы): товар, склад, регион, цена, отмена; "
                        "итоги по числу и сумме. Только боевой токен (у WB нет песочницы статистики), лимит WB — "
                        "1 запрос в минуту. Данных покупателя нет. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {
             **_LIST, "date_from": {"type": "string", "description": "ГГГГ-ММ-ДД, время Москвы"}}},
         "fn": list_orders},
        {"name": f"{SVC}_propose_feedback_answer",
         "description": "Черновик ответа на отзыв (id из list_feedbacks). Сам не публикует — ждёт «Да» человека.",
         "inputSchema": _ANSWER, "fn": propose_feedback_answer},
        {"name": f"{SVC}_propose_question_answer",
         "description": "Черновик ответа на вопрос (id из list_questions). Сам не публикует — ждёт «Да» человека.",
         "inputSchema": _ANSWER, "fn": propose_question_answer},
        {"name": f"{SVC}_apply",
         "description": "Опубликовать черновик ответа, подтверждённый человеком (id черновика из propose_*). "
                        "Работает только при GAS_WILDBERRIES_WRITE=1.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
         "fn": apply}],
}

if __name__ == "__main__":
    sys.exit(_core.main(SERVER, SVC))
