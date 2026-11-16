"""Telegram Business для пульта: входящие из рабочих чатов владельца (или клиента), подключённых к боту через
«Настройки → Telegram для бизнеса → Чат-боты». Чтение; ответ клиенту — только черновик и подтверждение человека.

Бот видит только чаты, которые выбрал владелец аккаунта, и отвечает, только если владелец включил право «отвечать»
(``rights.can_reply``). Это официальная замена Telethon для рабочих переписок (задача gvriil/gas-pult#201).

Ключ — токен бота одной строкой в ``~/.config/gastech-mcp/tg-business-bot.token`` (путь — ``GAS_TGBIZ_KEY_FILE``).
Адрес — ``GAS_TGBIZ_BASE`` (по умолчанию https://api.telegram.org). Контракт — docs/CONNECTORS.md,
описание — docs/connectors/tgbiz.md. Bot API 10.4: https://core.telegram.org/bots/api (сверено 16.11.2026).
**Не проверено на живом боте** — fixtures собраны по описанию типов в документации.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

if __package__:
    from . import _core
else:                                                  # запуск файлом: python3 tgbiz_mcp.py
    import _core

SVC = "tgbiz"
NAME = "Telegram"
KEY_FILE = "tg-business-bot.token"                     # имя из задачи #201 и QUEUE.md, а не tgbiz.token
THROTTLE = _core.Throttle(20, 1.0)                     # Bot API: ~30 сообщений/с на бота; берём с запасом
BUSINESS_UPDATES = ["business_connection", "business_message", "edited_business_message",
                    "deleted_business_messages"]
TEXT_MAX = 1000                                        # длинное письмо клиента режем: модели хватает начала
_TOKEN = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,}$")
_CONN = re.compile(r"^[A-Za-z0-9_\-+/=]{1,128}$")


def _key() -> str:
    os.environ.setdefault(f"GAS_{SVC.upper()}_KEY_FILE", str(_core.SECRETS_DIR / KEY_FILE))
    key = _core.read_secret(SVC)
    if not _TOKEN.match(key):
        raise _core.ToolError(f"в файле {KEY_FILE} должен быть токен бота одной строкой (вида 123456:ABC…) "
                              "— см. docs/connectors/tgbiz.md")
    return key


def _keys() -> list[str]:
    try:
        return [_key()]
    except _core.ToolError:
        return []


def _api(method: str, tg_method: str, *, query: dict | None = None, body: dict | None = None):
    """Вызов Bot API. Токен — в пути (так устроен Bot API), поэтому ошибки и ответы чистятся от него ``hide``."""
    key = _key()
    url = f"{_core.base_url(SVC, 'https://api.telegram.org')}/bot{key}/{tg_method}"
    try:
        r = _core.http(method, url, query=query, body=body, keys=[key], throttle=THROTTLE, service=NAME)
    except _core.ToolError as e:
        t = str(e)
        if " 409" in t:
            t += " (у бота включён вебхук или его уже читает другая программа — getUpdates недоступен)"
        raise _core.ToolError(_core.hide(t, key)) from None
    if not isinstance(r, dict) or not r.get("ok"):
        desc = r.get("description", "") if isinstance(r, dict) else str(r)[:200]
        raise _core.ToolError(_core.hide(f"{NAME}: ошибка Bot API: {desc}", key))
    return r.get("result")


def _iso(ts) -> str:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(int(ts)))
    except (TypeError, ValueError):
        return ""


def _who(u: dict | None) -> dict:
    u = u or {}
    name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or u.get("title", "")
    out = {"id": u.get("id"), "name": name}
    if u.get("username"):
        out["username"] = "@" + u["username"]
    return out


def _limit(a: dict, default: int = 20) -> int:
    return max(1, min(int(a.get("limit", default)), 100))


def _int(v, what: str) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        raise _core.ToolError(f"{what}: нужно целое число") from None


def _conn_id(v) -> str:
    s = str(v or "").strip()
    if not _CONN.match(s):
        raise _core.ToolError("connection_id: нужен id подключения из tgbiz_list_connections")
    return s


def _content(m: dict) -> str:
    """Текст сообщения; для вложений — пометка вида «[фото] подпись». Файлы не скачиваем."""
    kinds = {"photo": "фото", "document": "файл", "voice": "голосовое", "video": "видео", "video_note": "кружок",
             "audio": "аудио", "sticker": "стикер", "location": "геоточка", "contact": "контакт", "poll": "опрос"}
    text = m.get("text") or m.get("caption") or ""
    tag = next((f"[{v}]" for k, v in kinds.items() if k in m), "")
    s = f"{tag} {text}".strip()
    return s if len(s) <= TEXT_MAX else s[:TEXT_MAX] + f"… (+{len(s) - TEXT_MAX} симв.)"


def _updates() -> list[dict]:
    """Бизнес-апдейты из очереди Bot API **без подтверждения** (без offset): Telegram их не удаляет, их видит и
    следующий вызов. Telegram хранит неподтверждённые апдейты до 24 ч и отдаёт не больше 100 самых старых."""
    res = _api("GET", "getUpdates", query={"limit": 100, "timeout": 0,
                                           "allowed_updates": json.dumps(BUSINESS_UPDATES)})
    return res if isinstance(res, list) else []


def _msg_row(upd_id: int, kind: str, m: dict) -> dict:
    chat, frm = m.get("chat") or {}, m.get("from") or {}
    incoming = bool(frm.get("id")) and frm.get("id") == chat.get("id") and not m.get("sender_business_bot")
    row = {"update_id": upd_id, "kind": kind, "connection_id": m.get("business_connection_id", ""),
           "chat": _who(chat), "message_id": m.get("message_id"), "date": _iso(m.get("date")),
           "direction": "входящее" if incoming else "исходящее", "text": _content(m)}
    if kind == "изменено" and m.get("edit_date"):
        row["edited"] = _iso(m["edit_date"])
    if (m.get("reply_to_message") or {}).get("message_id"):
        row["reply_to"] = m["reply_to_message"]["message_id"]
    return row


def list_messages(a: dict):
    limit = _limit(a)
    chat = _int(a["chat_id"], "chat_id") if a.get("chat_id") not in (None, "") else None
    conn = _conn_id(a["connection_id"]) if a.get("connection_id") else None
    only_in = bool(a.get("only_incoming", False))
    rows: list[dict] = []
    for u in _updates():
        uid = u.get("update_id")
        if "business_message" in u:
            rows.append(_msg_row(uid, "новое", u["business_message"]))
        elif "edited_business_message" in u:
            rows.append(_msg_row(uid, "изменено", u["edited_business_message"]))
        elif "deleted_business_messages" in u:
            d = u["deleted_business_messages"]
            rows.append({"update_id": uid, "kind": "удалено", "connection_id": d.get("business_connection_id", ""),
                         "chat": _who(d.get("chat")), "message_ids": d.get("message_ids", [])})
    rows = [r for r in rows if (chat is None or r["chat"]["id"] == chat)
            and (conn is None or r["connection_id"] == conn)
            and (not only_in or r.get("direction") == "входящее")]
    total = len(rows)
    out = {"messages": rows[-limit:], "total": total,
           "note": "Telegram хранит неподтверждённые апдейты до 24 ч и отдаёт до 100 самых старых; коннектор их "
                   "не подтверждает и не сохраняет — история старше суток в пульте пока не видна."}
    if total > limit:
        out["more"] = f"показаны последние {limit} из {total}; увеличьте limit (до 100) или задайте chat_id"
    return out


def _conn_row(c: dict) -> dict:
    rights = c.get("rights") or {}
    return {"id": c.get("id", ""), "owner": _who(c.get("user")), "owner_chat_id": c.get("user_chat_id"),
            "connected": _iso(c.get("date")), "enabled": bool(c.get("is_enabled")),
            "can_reply": bool(rights.get("can_reply")),
            "rights": sorted(k for k, v in rights.items() if v is True)}


def get_connection(a: dict):
    return _conn_row(_api("GET", "getBusinessConnection",
                          query={"business_connection_id": _conn_id(a.get("connection_id"))}) or {})


def list_connections(a: dict):
    """Подключения: события business_connection из очереди + id из сообщений, уточнённые getBusinessConnection."""
    limit = _limit(a, 10)
    seen: dict[str, dict] = {}
    ids: list[str] = []
    for u in _updates():
        c = u.get("business_connection")
        if c and c.get("id"):
            seen[c["id"]] = _conn_row(c)
        for k in ("business_message", "edited_business_message", "deleted_business_messages"):
            cid = (u.get(k) or {}).get("business_connection_id")
            if cid and cid not in ids:
                ids.append(cid)
    for cid in ids:
        if cid not in seen and len(seen) < limit:
            seen[cid] = get_connection({"connection_id": cid})
    rows = list(seen.values())[:limit]
    return {"connections": rows,
            "note": "подключений нет в очереди за 24 ч — напишите боту в тестовый чат или переподключите бота"
                    if not rows else "can_reply=false — ответ из пульта невозможен, пока владелец не включит право"}


def get_bot(a: dict):
    me = _api("GET", "getMe") or {}
    return {"bot": _who(me), "can_connect_to_business": bool(me.get("can_connect_to_business")),
            "hint": "" if me.get("can_connect_to_business") else
            "включите у бота режим Telegram Business в @BotFather (настройки бота; название пункта не проверено)"}


def propose_reply(a: dict):
    conn = _conn_id(a.get("connection_id"))
    chat = _int(a.get("chat_id"), "chat_id")
    text = str(a.get("text") or "").strip()
    if not 1 <= len(text) <= 4096:
        raise _core.ToolError("text: от 1 до 4096 символов")
    params = {"connection_id": conn, "chat_id": chat, "text": text}
    if a.get("reply_to") not in (None, ""):
        params["reply_to"] = _int(a["reply_to"], "reply_to")
    c = get_connection({"connection_id": conn})          # только чтение: проверить, что ответить вообще можно
    if not c["enabled"]:
        raise _core.ToolError("подключение выключено владельцем аккаунта — ответить нельзя")
    if not c["can_reply"]:
        raise _core.ToolError("у бота нет права «отвечать» в этом подключении — его включает владелец аккаунта "
                              "(Настройки → Telegram для бизнеса → Чат-боты)")
    preview = text if len(text) <= 300 else text[:300] + "…"
    return _core.propose(SVC, "reply", params,
                         f"ответ в Telegram от имени {c['owner']['name'] or 'владельца'} в чат {chat}: «{preview}»")


def apply(a: dict):
    rec = _core.take_confirmed(SVC, a.get("id", ""))
    p = rec["params"]
    body = {"business_connection_id": p["connection_id"], "chat_id": p["chat_id"], "text": p["text"]}
    if p.get("reply_to"):
        body["reply_parameters"] = {"message_id": p["reply_to"], "allow_sending_without_reply": True}
    m = _api("POST", "sendMessage", body=body) or {}
    return {"done": rec["summary"], "message_id": m.get("message_id"), "date": _iso(m.get("date"))}


_OBJ = {"type": "object"}
SERVER = {
    "name": f"gas-pult-{SVC}",
    "instructions": "Telegram Business: входящие из рабочих чатов, подключённых к боту. Чтение; ответ клиенту — "
                    "только черновик tgbiz_propose_reply и подтверждение человека в пульте, затем tgbiz_apply.",
    "keys": _keys,
    "tools": [
        {"name": f"{SVC}_list_messages",
         "description": "Сообщения из подключённых рабочих чатов за последние 24 ч: новые, изменённые, удалённые; "
                        "кто, когда, текст (вложения — пометкой, файлы не скачивает). Ничего не отмечает "
                        "прочитанным и не удаляет из очереди Telegram.",
         "inputSchema": _OBJ | {"properties": {
             "limit": {"type": "integer", "default": 20},
             "chat_id": {"type": "integer", "description": "только этот чат"},
             "connection_id": {"type": "string", "description": "только это подключение"},
             "only_incoming": {"type": "boolean", "default": False, "description": "только от клиентов"}}},
         "fn": list_messages},
        {"name": f"{SVC}_list_connections",
         "description": "Подключения бота к бизнес-аккаунтам: чей аккаунт, включено ли, есть ли право отвечать. "
                        "Ничего не меняет.",
         "inputSchema": _OBJ | {"properties": {"limit": {"type": "integer", "default": 10}}},
         "fn": list_connections},
        {"name": f"{SVC}_get_connection",
         "description": "Одно подключение по id: владелец, включено, права бота. Ничего не меняет.",
         "inputSchema": _OBJ | {"properties": {"connection_id": {"type": "string"}}, "required": ["connection_id"]},
         "fn": get_connection},
        {"name": f"{SVC}_get_bot",
         "description": "Проверка ключа: имя бота и включён ли у него Business Mode. Ничего не меняет.",
         "inputSchema": _OBJ | {"properties": {}}, "fn": get_bot},
        {"name": f"{SVC}_propose_reply",
         "description": "Черновик ответа клиенту от имени владельца аккаунта. Сам ничего не отправляет: человек "
                        "подтверждает в пульте, затем tgbiz_apply. Проверяет, что у бота есть право отвечать.",
         "inputSchema": _OBJ | {"properties": {
             "connection_id": {"type": "string"}, "chat_id": {"type": "integer"},
             "text": {"type": "string", "description": "1–4096 символов"},
             "reply_to": {"type": "integer", "description": "message_id, на который ответ"}},
             "required": ["connection_id", "chat_id", "text"]},
         "fn": propose_reply},
        {"name": f"{SVC}_apply",
         "description": "Отправить ответ, подтверждённый человеком (id черновика). Без подтверждения и при "
                        "GAS_TGBIZ_WRITE=0 — ошибка.",
         "inputSchema": _OBJ | {"properties": {"id": {"type": "string"}}, "required": ["id"]},
         "fn": apply}],
}

if __name__ == "__main__":
    sys.exit(_core.main(SERVER, SVC))
