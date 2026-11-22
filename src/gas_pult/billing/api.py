"""HTTP-слой платежей для панели — единственное, что импортирует ``webapp``. Права — только владелец
(``access.BILLING`` входит в ``OWNER_ONLY``); изменения — ещё и через подтверждение кодом (``access.CONFIRM``).

Каждое изменение требует ``key`` — ключ операции (панель создаёт его на нажатие): повтор запроса не дублирует.
"""

from pathlib import Path

from . import money, provider, store

GET = ("/api/billing/plans", "/api/billing/invoices", "/api/billing/invoice")
POST = ("/api/billing/plan", "/api/billing/invoice/new", "/api/billing/invoice/issue", "/api/billing/invoice/pay",
        "/api/billing/invoice/void")
PATHS = GET + POST


def _int(v, name: str) -> int:
    if isinstance(v, bool) or not (isinstance(v, int) or (isinstance(v, str) and v.isdigit())):
        raise ValueError("нужно целое: " + name)
    return int(v)


def _view(inv: dict) -> dict:
    """Счёт для панели: суммы и строкой (без float), чтобы интерфейс ничего не считал сам."""
    cur = inv["currency"]
    out = {**inv, "total_text": money.fmt(inv["total"], cur)}
    if "balance" in inv:
        out["balance_text"] = money.fmt(inv["balance"], cur)
    if "items" in inv:
        out["items"] = [{**x, "amount_text": money.fmt(x["amount"], cur)} for x in inv["items"]]
    if "journal" in inv:
        out["journal"] = [{**x, "amount_text": money.fmt(x["amount"], cur)} for x in inv["journal"]]
    return out


def get(data: Path, path: str, q: dict) -> dict:
    if path not in GET:
        raise KeyError(path)
    con = store.connect(data)
    try:
        if path == "/api/billing/plans":
            return {"plans": [{**p, "amount_text": money.fmt(p["amount"], p["currency"])} for p in store.plans(con)],
                    "provider": provider.get().status(), "currencies": sorted(money.MINOR)}
        if path == "/api/billing/invoices":
            return {"invoices": [_view(x) for x in store.invoices(con)], "provider": provider.get().status()}
        if path == "/api/billing/invoice":
            return _view(store.invoice(con, _int(q.get("id"), "id")))
    finally:
        con.close()
    raise KeyError(path)


def post(data: Path, path: str, b: dict, actor: str = "") -> dict:
    if not isinstance(b, dict):
        raise ValueError("тело запроса — объект")
    if path not in POST:
        raise KeyError(path)
    con = store.connect(data)
    try:
        key = b.get("key")
        if path == "/api/billing/plan":
            amount = money.to_minor(str(b.get("price", "")), str(b.get("currency", ""))) if "price" in b \
                else _int(b.get("amount"), "amount")
            return store.add_plan(con, b.get("code"), b.get("title"), amount, str(b.get("currency", "")),
                                  str(b.get("period", "")), key=key, actor=actor)
        if path == "/api/billing/invoice/new":
            lines = []
            for x in b.get("lines") or []:
                if not isinstance(x, dict):
                    raise ValueError("строка счёта — объект")
                x = dict(x)
                if "price" in x:                    # человек ввёл «12.50» — без округления, лишние знаки — ошибка
                    x["unit"] = money.to_minor(str(x.pop("price")), str(b.get("currency", "")))
                if "qty" in x:
                    x["qty"] = _int(x["qty"], "qty")
                lines.append(x)
            return _view(store.create(con, b.get("client"), str(b.get("currency", "")), lines, key=key,
                                      space=b.get("space") or "", due_days=_int(b.get("due_days", 14), "due_days"),
                                      actor=actor))
        iid = _int(b.get("id"), "id")
        if path == "/api/billing/invoice/issue":
            return _view(store.issue(con, iid, key=key, actor=actor))
        if path == "/api/billing/invoice/pay":
            return _view(store.mark_paid(con, iid, key=key, reason=b.get("reason"), actor=actor,
                                         ref=str(b.get("ref") or "")))
        if path == "/api/billing/invoice/void":
            return _view(store.void(con, iid, key=key, reason=b.get("reason"), actor=actor))
    finally:
        con.close()
    raise KeyError(path)
