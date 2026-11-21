"""Ozon Seller для пульта: остатки, цены, заказы (отправления FBS и FBO), отзывы — чтение. Запись — только ответ
на отзыв: черновик → «Да» человека → публикация. Цены, остатки, поставки, карточки, отмены не меняем.

Ключ — JSON ``{"client_id": "...", "api_key": "..."}`` в ``~/.config/gastech-mcp/ozon.token`` (путь —
``GAS_OZON_KEY_FILE``). Адрес — ``https://api-seller.ozon.ru``, ``GAS_OZON_BASE`` подменяет (тесты). Песочницы у Ozon
Seller API нет: ключ всегда боевой, поэтому — роль «только чтение» (см. docs/connectors/ozon.md).
Контракт — docs/CONNECTORS.md. Документация — https://docs.ozon.ru/api/seller/ (сайт закрыт антибот-проверкой для
программ; методы и примеры сверены по её индексу в Context7 «/websites/ozon_ru_api_seller» и зеркалу
github.com/etozhearut/ozon-seller-api, docs/14-fbs.md, 16-fbo.md, 06-pricesandstocksapi.md, 37-reviewapi.md —
19.11.2026). **Не проверено на песочнице** — ключа ещё нет.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import UTC, datetime, timedelta, timezone

if __package__:
    from . import _core
else:                                                  # запуск файлом: python3 ozon_mcp.py
    import _core

SVC = "ozon"
NAME = "Ozon"
# Документация, «Все методы»: не больше 50 запросов в секунду на один Client-Id, у методов бывают свои лимиты,
# при перегрузке — ошибка «Circle is open». Держим заметно ниже.
THROTTLE = _core.Throttle(10, 1.0)
MSK = timezone(timedelta(hours=3))
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REVIEW_ID = re.compile(r"^[0-9A-Za-z-]{6,64}$")
STATUSES = ("awaiting_registration", "acceptance_in_progress", "awaiting_approve", "awaiting_packaging",
            "awaiting_deliver", "arbitration", "client_arbitration", "delivering", "driver_pickup", "delivered",
            "cancelled", "not_accepted", "sent_by_seller")
REVIEW_STATUSES = ("NEW", "VIEWED", "PROCESSED")


def _creds() -> tuple[str, str, str]:
    raw = _core.read_secret(SVC)
    try:
        d = json.loads(raw)
        cid, key = str(d["client_id"]).strip(), str(d["api_key"]).strip()
    except (ValueError, TypeError, KeyError):
        raise _core.ToolError('файл ключа ozon.token — JSON {"client_id": "...", "api_key": "..."}, '
                              "см. docs/connectors/ozon.md") from None
    if not cid or not key:
        raise _core.ToolError("в ozon.token пустой client_id или api_key")
    return cid, key, raw


def _api(path: str, body: dict):
    cid, key, raw = _creds()
    return _core.http("POST", _core.base_url(SVC, "https://api-seller.ozon.ru") + path,
                      headers={"Client-Id": cid, "Api-Key": key}, body=body,
                      keys=[*_core.secret_values(raw), cid, key], throttle=THROTTLE, service=NAME)


def _limit(a: dict, default: int = 20) -> int:
    return max(1, min(int(a.get("limit", default)), 100))


def _cursor(a: dict) -> str:
    return str(a.get("cursor") or "")[:500]


def _day(s: str, what: str) -> datetime:
    if not _DATE.match(str(s)):
        raise _core.ToolError(f"{what}: дата в виде ГГГГ-ММ-ДД")
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=MSK)


def _utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _product_link(sku) -> str | None:
    # Формат ссылки — с сайта Ozon, не из документации API.
    return f"https://www.ozon.ru/product/{sku}/" if sku else None


def _product_filter(a: dict) -> dict:
    f = {"visibility": "ALL"}
    if a.get("offer_id"):
        f["offer_id"] = [str(a["offer_id"])]
    return f


def _more(out: dict, rows: list, limit: int, cursor: str | None, has_next: bool | None = None) -> dict:
    if cursor and (has_next if has_next is not None else len(rows) == limit):
        out["more"] = f"показано {len(rows)}; следующие — cursor={cursor}"
    return out


# ---------- чтение ----------
def list_stocks(a: dict):
    limit = _limit(a)
    data = _api("/v4/product/info/stocks", {"filter": _product_filter(a), "limit": limit, "cursor": _cursor(a)})
    rows = []
    for it in data.get("items") or []:
        by = {}
        for s in it.get("stocks") or []:
            t = by.setdefault(str(s.get("type") or "?"), {"present": 0, "reserved": 0})
            t["present"] += int(s.get("present") or 0)
            t["reserved"] += int(s.get("reserved") or 0)
        for t in by.values():
            t["available"] = t["present"] - t["reserved"]
        sku = next((s.get("sku") for s in it.get("stocks") or [] if s.get("sku")), None)
        rows.append({"product_id": it.get("product_id"), "offer_id": it.get("offer_id"), "sku": sku,
                     "stocks": by, "link": _product_link(sku)})
    out = {"total_products": data.get("total_items", data.get("total")),
           "note": "present — на складе, reserved — в резерве, available — можно продать; fbo — склады Ozon, "
                   "fbs/rfbs — ваш склад", "rows": rows}
    return _more(out, rows, limit, data.get("cursor"))


def list_prices(a: dict):
    limit = _limit(a)
    data = _api("/v5/product/info/prices", {"filter": _product_filter(a), "limit": limit, "cursor": _cursor(a)})
    rows = []
    for it in data.get("items") or []:
        p = it.get("price") or {}
        idx = it.get("price_indexes") or {}
        acts = (it.get("marketing_actions") or {}).get("actions") or []
        rows.append({"product_id": it.get("product_id"), "offer_id": it.get("offer_id"),
                     "currency": p.get("currency_code"), "price": p.get("price"), "old_price": p.get("old_price"),
                     "min_price": p.get("min_price"), "net_price": p.get("net_price"),
                     "price_index": idx.get("color_index"),
                     "commission_fbo_pct": (it.get("commissions") or {}).get("sales_percent_fbo"),
                     "commission_fbs_pct": (it.get("commissions") or {}).get("sales_percent_fbs"),
                     "actions": [x.get("title") for x in acts[:5]]})
    out = {"total_products": data.get("total_items", data.get("total")),
           "note": "price — цена с вашей скидкой, old_price — зачёркнутая, min_price — ниже неё Ozon в акциях не "
                   "опустит; price_index — индекс цен Ozon (GREEN — выгодная)", "rows": rows}
    return _more(out, rows, limit, data.get("cursor"))


def list_orders(a: dict):
    scheme = str(a.get("scheme") or "fbs").lower()
    if scheme not in ("fbs", "fbo"):
        raise _core.ToolError("scheme — fbs (ваш склад) или fbo (склад Ozon)")
    limit = _limit(a)
    now = datetime.now(MSK)
    since = _day(a["date_from"], "date_from") if a.get("date_from") else \
        now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    to = _day(a["date_to"], "date_to") + timedelta(days=1) if a.get("date_to") else now
    if to <= since:
        raise _core.ToolError("date_to раньше date_from")
    if to - since > timedelta(days=365):
        raise _core.ToolError("период — не больше года (ограничение Ozon)")
    flt: dict = {"since": _utc(since), "to": _utc(to)}
    if a.get("status"):
        st = str(a["status"]).strip()
        if st not in STATUSES:
            raise _core.ToolError(f"status — один из: {', '.join(STATUSES)}")
        flt["statuses"] = [st]
    # Без "with": адрес, имя, телефон покупателя и юр. данные не запрашиваем.
    body = {"filter": flt, "limit": limit, "cursor": _cursor(a), "sort_dir": "DESC"}
    data = _api("/v4/posting/fbs/list" if scheme == "fbs" else "/v3/posting/fbo/list", body)
    rows, total = [], 0.0
    for p in data.get("postings") or []:
        items = [{"offer_id": x.get("offer_id"), "name": x.get("name"), "sku": x.get("sku"),
                  "qty": x.get("quantity"), "price": _num((x.get("price") or {}).get("amount")),
                  "currency": (x.get("price") or {}).get("currency")} for x in (p.get("products") or [])[:20]]
        s = round(sum(i["price"] * int(i["qty"] or 0) for i in items), 2)
        cancelled = p.get("status") == "cancelled"
        total += 0 if cancelled else s
        rows.append({"posting_number": p.get("posting_number"), "order_number": p.get("order_number"),
                     "status": p.get("status"), "substatus": p.get("substatus"),
                     "created": p.get("in_process_at") or p.get("created_at"),
                     "shipment_date": p.get("shipment_date"), "sum": s, "products": items})
    out = {"scheme": scheme, "since_utc": flt["since"], "to_utc": flt["to"], "count": len(rows),
           "sum_not_cancelled": round(total, 2),
           "note": "время — UTC (так отдаёт Ozon); сумма — цена × количество по строкам, без комиссий Ozon; "
                   "данных покупателя нет", "rows": rows}
    return _more(out, rows, limit, data.get("cursor"), bool(data.get("has_next")))


def list_reviews(a: dict):
    limit = _limit(a)
    filters: dict = {}
    if a.get("status"):
        st = str(a["status"]).upper()
        if st not in REVIEW_STATUSES:
            raise _core.ToolError("status — NEW (новые), VIEWED (просмотренные) или PROCESSED (обработанные)")
        filters["status"] = st
    if a.get("sku"):
        filters["sku"] = [int(a["sku"])]
    body = {"filters": filters, "limit": max(20, limit), "sort_dir": "DESC"}  # у Ozon минимум 20
    if a.get("last_id"):
        body["last_id"] = str(a["last_id"])[:100]
    data = _api("/v2/review/list", body)
    rows = [{"id": r.get("id"), "sku": r.get("sku"), "date": r.get("published_at"), "rating": r.get("rating"),
             "text": (r.get("text") or "")[:1000], "status": r.get("status"),
             "comments": r.get("comments_amount"), "photos": r.get("photos_amount"),
             "videos": r.get("videos_amount"), "order_status": r.get("order_status"),
             "link": _product_link(r.get("sku"))} for r in (data.get("reviews") or [])[:limit]]
    out = {"note": "имя покупателя не отдаём; ответить — ozon_propose_review_comment", "rows": rows}
    if data.get("has_next") and data.get("last_id"):
        out["more"] = f"показано {len(rows)}; следующие — last_id={data['last_id']}"
    return out


# ---------- запись: только ответ на отзыв, через подтверждение ----------
def propose_review_comment(a: dict):
    rid, text = str(a.get("review_id", "")).strip(), str(a.get("text", "")).strip()
    if not _REVIEW_ID.match(rid):
        raise _core.ToolError("review_id — id отзыва из ozon_list_reviews")
    if not 2 <= len(text) <= 3000:
        raise _core.ToolError("текст ответа — от 2 до 3000 символов")
    return _core.propose(SVC, "review_comment", {"review_id": rid, "text": text},
                         f"Ответ на отзыв {rid} на Ozon (увидят все покупатели; отзыв станет «обработан»): "
                         f"«{text[:300]}»")


def apply(a: dict):
    rec = _core.take_confirmed(SVC, a.get("id", ""))
    p = rec["params"]
    if rec["action"] != "review_comment":
        raise _core.ToolError(f"неизвестное действие черновика: {rec['action']}")
    res = _api("/v1/review/comment/create",
               {"review_id": p["review_id"], "text": p["text"], "mark_review_as_processed": True})
    return {"done": rec["summary"], "comment_id": (res or {}).get("comment_id") if isinstance(res, dict) else None,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


_PRODUCTS = {"limit": {"type": "integer", "default": 20, "description": "сколько строк, 1–100"},
             "cursor": {"type": "string", "description": "следующая страница — из поля more прошлого ответа"},
             "offer_id": {"type": "string", "description": "один артикул продавца (необязательно)"}}

SERVER = {
    "name": f"gas-pult-{SVC}",
    "instructions": "Ozon Seller: остатки, цены, заказы FBS/FBO, отзывы — чтение. Ответ на отзыв — только черновик, "
                    "публикует человек после «Да». Цены, остатки, поставки, карточки, отмены не меняет.",
    "keys": lambda: _core.secret_values(_core.read_secret(SVC)),
    "tools": [
        {"name": f"{SVC}_list_stocks",
         "description": "Остатки товаров Ozon по схемам (FBO — склады Ozon, FBS/rFBS — ваш склад): на складе, "
                        "в резерве, можно продать. Остатки не меняет.",
         "inputSchema": {"type": "object", "properties": _PRODUCTS}, "fn": list_stocks},
        {"name": f"{SVC}_list_prices",
         "description": "Цены товаров Ozon: цена, зачёркнутая, минимальная, индекс цен, комиссии FBO/FBS, акции. "
                        "Цены не меняет.",
         "inputSchema": {"type": "object", "properties": _PRODUCTS}, "fn": list_prices},
        {"name": f"{SVC}_list_orders",
         "description": "Заказы (отправления) Ozon за период, свежие сверху: номер, статус, товары, сумма. "
                        "scheme=fbs — ваш склад (по умолчанию), fbo — склад Ozon. По умолчанию — со вчера. "
                        "Данных покупателя нет. Ничего не меняет, заказы не собирает и не отменяет.",
         "inputSchema": {"type": "object", "properties": {
             "scheme": {"type": "string", "enum": ["fbs", "fbo"], "default": "fbs"},
             "date_from": {"type": "string", "description": "ГГГГ-ММ-ДД, время Москвы"},
             "date_to": {"type": "string", "description": "ГГГГ-ММ-ДД включительно (по умолчанию — сейчас)"},
             "status": {"type": "string", "description": "один статус Ozon, напр. awaiting_packaging"},
             "limit": {"type": "integer", "default": 20}, "cursor": {"type": "string"}}},
         "fn": list_orders},
        {"name": f"{SVC}_list_reviews",
         "description": "Отзывы покупателей Ozon, свежие сверху: оценка, текст, SKU, статус (NEW/VIEWED/PROCESSED). "
                        "Нужна подписка Ozon «Управление отзывами» или Premium Pro. Ничего не меняет.",
         "inputSchema": {"type": "object", "properties": {
             "status": {"type": "string", "enum": list(REVIEW_STATUSES)},
             "sku": {"type": "integer", "description": "SKU Ozon (необязательно)"},
             "limit": {"type": "integer", "default": 20}, "last_id": {"type": "string"}}},
         "fn": list_reviews},
        {"name": f"{SVC}_propose_review_comment",
         "description": "Черновик ответа на отзыв (review_id из ozon_list_reviews). Сам не публикует — ждёт «Да» "
                        "человека.",
         "inputSchema": {"type": "object", "properties": {"review_id": {"type": "string"}, "text": {"type": "string"}},
                         "required": ["review_id", "text"]}, "fn": propose_review_comment},
        {"name": f"{SVC}_apply",
         "description": "Опубликовать черновик ответа, подтверждённый человеком (id черновика из propose). "
                        "Работает только при GAS_OZON_WRITE=1.",
         "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
         "fn": apply}],
}

if __name__ == "__main__":
    sys.exit(_core.main(SERVER, SVC))
