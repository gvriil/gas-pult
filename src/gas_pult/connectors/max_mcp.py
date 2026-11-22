"""MAX (мессенджер) для пульта: входящие боту организации — личные диалоги клиентов и чаты, где бот администратор.
Чтение; ответ клиенту — только черновик и подтверждение человека.

Ключ — токен бота одной строкой в ``~/.config/gastech-mcp/max.token`` (путь — ``GAS_MAX_KEY_FILE``); токен выдаёт
business.max.ru → Чат-боты → бот → Настройки (нужен верифицированный профиль организации, ИП или самозанятого).
Адрес — ``GAS_MAX_BASE`` (по умолчанию https://platform-api2.max.ru). Контракт — docs/CONNECTORS.md, описание —
docs/connectors/max.md. Источник — официальная схема OpenAPI MAX Bot API v0.0.34
(https://github.com/max-messenger/api-schema, коммит 0016ff3) и https://dev.max.ru/docs-api (сверено 20.11.2026).
**Не проверено на песочнице** (у MAX её нет; ключа пока нет) — fixtures собраны по схеме, данные выдуманные.
"""

from __future__ import annotations

import re
import sys
import time

if __package__:
    from . import _core
else:                                                  # запуск файлом: python3 max_mcp.py
    import _core

SVC = "max"
NAME = "MAX"
THROTTLE = _core.Throttle(25, 1.0)                     # лимит MAX — 30 запросов/с на platform-api2; берём с запасом
READ_TYPES = ["message_created", "message_edited", "message_removed", "bot_started", "bot_stopped"]
TEXT_MAX = 1000                                        # длинное сообщение режем: модели хватает начала
SEND_MAX = 4000                                        # NewMessageBody.text: maxLength 4000
_MID = re.compile(r"^(mid\.)?[A-Za-z0-9_\-]{1,128}$")  # MessageId: pattern (mid.)?[a-zA-Z0-9_\-]+
_TOKEN = re.compile(r"^\S{16,}$")                      # формат токена в документации не описан: «без пробелов»


def _key() -> str:
    key = _core.read_secret(SVC)
    if not _TOKEN.match(key):
        raise _core.ToolError("в файле max.token должен быть токен бота одной строкой без пробелов "
                              "— см. docs/connectors/max.md")
    return key


def _keys() -> list[str]:
    try:
        return [_key()]
    except _core.ToolError:
        return []


def _api(method: str, path: str, *, query: dict | None = None, body: dict | None = None):
    """Вызов MAX Bot API. Токен — в заголовке ``Authorization`` как есть, без «Bearer» (так требует MAX; передача
    токена в адресе запроса MAX больше не поддерживает)."""
    key = _key()
    try:
        r = _core.http(method, _core.base_url(SVC, "https://platform-api2.max.ru") + path, query=query, body=body,
                       headers={"Authorization": key}, keys=[key], throttle=THROTTLE, service=NAME)
    except _core.ToolError as e:
        t = str(e)
        if " 403" in t:
            t += " (пользователь остановил бота или у бота нет доступа к чату — в группе нужен админ с правом " \
                 "read_all_messages)"
        raise _core.ToolError(_core.hide(t, key)) from None
    if isinstance(r, dict) and r.get("success") is False:  # часть методов MAX отвечает ошибкой с кодом 200
        raise _core.ToolError(_core.hide(f"{NAME}: {r.get('code', '')} {r.get('message', '')}".strip(), key))
    if not isinstance(r, dict):
        raise _core.ToolError(f"{NAME}: неожиданный ответ сервиса")
    return r


def _iso(ms) -> str:
    """MAX отдаёт время в миллисекундах Unix."""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(int(ms) / 1000))
    except (TypeError, ValueError, OverflowError):
        return ""


def _who(u: dict | None) -> dict:
    u = u or {}
    name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or u.get("name") or ""
    out = {"id": u.get("user_id"), "name": name}
    if u.get("username"):
        out["username"] = "@" + u["username"]
    if u.get("is_bot"):
        out["bot"] = True
    return out


def _limit(a: dict, default: int = 20) -> int:
    return max(1, min(int(a.get("limit", default)), 100))


def _int(v, what: str) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        raise _core.ToolError(f"{what}: нужно целое число") from None


def _mid(v, what: str = "message_id") -> str:
    s = str(v or "").strip()
    if not _MID.match(s):
        raise _core.ToolError(f"{what}: нужен id сообщения (mid) из max_list_messages")
    return s


def _content(body: dict | None) -> str:
    """Текст сообщения; вложения — пометкой «[фото] подпись». Файлы не скачиваем, кнопки не показываем."""
    body = body or {}
    kinds = {"image": "фото", "video": "видео", "audio": "аудио", "file": "файл", "sticker": "стикер",
             "contact": "контакт", "share": "ссылка", "location": "геоточка"}
    tags = []
    for att in body.get("attachments") or []:
        t = kinds.get((att or {}).get("type", ""))
        if t and f"[{t}]" not in tags:
            tags.append(f"[{t}]")
    s = f"{' '.join(tags)} {body.get('text') or ''}".strip()
    return s if len(s) <= TEXT_MAX else s[:TEXT_MAX] + f"… (+{len(s) - TEXT_MAX} симв.)"


def _msg_row(m: dict, kind: str = "") -> dict:
    rcp, snd, body = m.get("recipient") or {}, m.get("sender"), m.get("body") or {}
    row = {"message_id": body.get("mid", ""), "chat_id": rcp.get("chat_id"), "chat_type": rcp.get("chat_type", ""),
           "from": _who(snd) if snd else {"name": "канал"}, "date": _iso(m.get("timestamp")),
           "direction": "исходящее" if (snd or {}).get("is_bot") else "входящее", "text": _content(body)}
    if kind:
        row = {"kind": kind, **row}
    link = m.get("link") or {}
    if link.get("type") == "reply" and (link.get("message") or {}).get("mid"):
        row["reply_to"] = link["message"]["mid"]
    elif link.get("type") == "forward":
        row["forwarded_from"] = _who(link.get("sender")).get("name") or "канал"
    if m.get("url"):
        row["url"] = m["url"]
    return row


def list_messages(a: dict):
    """Входящие боту за последние события: GET /updates **без marker** — MAX ничего не считает подтверждённым."""
    limit = _limit(a)
    chat = _int(a["chat_id"], "chat_id") if a.get("chat_id") not in (None, "") else None
    only_in = bool(a.get("only_incoming", False))
    res = _api("GET", "/updates", query={"limit": 100, "timeout": 0, "types": ",".join(READ_TYPES)})
    rows: list[dict] = []
    for u in res.get("updates") or []:
        t = u.get("update_type")
        if t in ("message_created", "message_edited") and u.get("message"):
            rows.append(_msg_row(u["message"], "новое" if t == "message_created" else "изменено"))
        elif t == "message_removed":
            rows.append({"kind": "удалено", "message_id": u.get("message_id", ""), "chat_id": u.get("chat_id"),
                         "date": _iso(u.get("timestamp"))})
        elif t in ("bot_started", "bot_stopped"):
            rows.append({"kind": "начал диалог" if t == "bot_started" else "остановил бота",
                         "chat_id": u.get("chat_id"), "from": _who(u.get("user")), "date": _iso(u.get("timestamp")),
                         **({"payload": str(u["payload"])[:200]} if u.get("payload") else {})})
    rows = [r for r in rows if (chat is None or r.get("chat_id") == chat)
            and (not only_in or r.get("direction") == "входящее")]
    total = len(rows)
    out = {"messages": rows[-limit:], "total": total,
           "note": "события из очереди MAX без подтверждения: коннектор их не забирает и не хранит. Long Polling MAX "
                   "ограничен по сроку хранения событий; историю чата — max_list_history."}
    if total > limit:
        out["more"] = f"показаны последние {limit} из {total}; увеличьте limit (до 100) или задайте chat_id"
    return out


def list_history(a: dict):
    """История одного чата: GET /messages?chat_id= (новые первыми). В группе и канале — только если бот админ."""
    chat = _int(a.get("chat_id"), "chat_id")
    q: dict = {"chat_id": chat, "count": _limit(a)}
    for k in ("before", "after"):
        if a.get(k) not in (None, ""):
            q[k] = _int(a[k], k)
    rows = [_msg_row(m) for m in _api("GET", "/messages", query=q).get("messages") or []]
    out = {"chat_id": chat, "messages": rows}
    if len(rows) == q["count"]:
        out["more"] = "есть ещё: повторите с before = время самого старого сообщения (мс Unix)"
    return out


def get_message(a: dict):
    return _msg_row(_api("GET", f"/messages/{_mid(a.get('message_id'))}"))


def _chat_row(c: dict) -> dict:
    out = {"chat_id": c.get("chat_id"), "type": c.get("type", ""), "status": c.get("status", ""),
           "title": c.get("title") or "", "participants": c.get("participants_count"),
           "last_event": _iso(c.get("last_event_time")), "public": bool(c.get("is_public"))}
    if c.get("dialog_with_user"):
        out["dialog_with"] = _who(c["dialog_with_user"])
    if c.get("link"):
        out["link"] = c["link"]
    return out


def get_chat(a: dict):
    return _chat_row(_api("GET", f"/chats/{_int(a.get('chat_id'), 'chat_id')}"))


def get_bot(a: dict):
    me = _api("GET", "/me")
    return {"bot": _who(me), "commands": [c.get("name") for c in me.get("commands") or [] if c.get("name")]}


def propose_reply(a: dict):
    chat = _int(a.get("chat_id"), "chat_id")
    text = str(a.get("text") or "").strip()
    if not 1 <= len(text) <= SEND_MAX:
        raise _core.ToolError(f"text: от 1 до {SEND_MAX} символов")
    params = {"chat_id": chat, "text": text}
    if a.get("reply_to") not in (None, ""):
        params["reply_to"] = _mid(a["reply_to"], "reply_to")
    c = get_chat({"chat_id": chat})                     # только чтение: можно ли вообще писать в этот чат
    if c["status"] != "active":
        why = {"suspended": "пользователь остановил бота", "removed": "бота удалили из чата",
               "left": "бот вышел из чата", "closed": "чат закрыт"}.get(c["status"], c["status"] or "неизвестно")
        raise _core.ToolError(f"ответить нельзя: {why}")
    if c["type"] == "channel":
        raise _core.ToolError("это канал: публикации в канал из пульта не делаем — только ответы в диалоги и чаты")
    who = (c.get("dialog_with") or {}).get("name") or c["title"] or str(chat)
    preview = text if len(text) <= 300 else text[:300] + "…"
    return _core.propose(SVC, "reply", params, f"ответ в MAX от бота в чат «{who}»: «{preview}»")


def apply(a: dict):
    rec = _core.take_confirmed(SVC, a.get("id", ""))
    p = rec["params"]
    body: dict = {"text": p["text"], "notify": True}
    if p.get("reply_to"):
        body["link"] = {"type": "reply", "mid": p["reply_to"]}
    m = _api("POST", "/messages", query={"chat_id": p["chat_id"]}, body=body).get("message") or {}
    return {"done": rec["summary"], "message_id": (m.get("body") or {}).get("mid", ""),
            "date": _iso(m.get("timestamp"))}


_OBJ = {"type": "object"}
SERVER = {
    "name": f"gas-pult-{SVC}",
    "instructions": "MAX: входящие боту организации (диалоги клиентов, чаты, где бот админ). Чтение; ответ клиенту — "
                    "только черновик max_propose_reply и подтверждение человека в пульте, затем max_apply.",
    "keys": _keys,
    "tools": [
        {"name": f"{SVC}_list_messages",
         "description": "Новые события бота: сообщения клиентов (новые, изменённые, удалённые), кто начал или "
                        "остановил диалог; кто, когда, текст (вложения — пометкой, файлы не скачивает). Ничего не "
                        "отмечает прочитанным и не забирает из очереди MAX.",
         "inputSchema": _OBJ | {"properties": {
             "limit": {"type": "integer", "default": 20},
             "chat_id": {"type": "integer", "description": "только этот чат"},
             "only_incoming": {"type": "boolean", "default": False, "description": "только от людей, не от бота"}}},
         "fn": list_messages},
        {"name": f"{SVC}_list_history",
         "description": "История одного чата, новые первыми (до 100). В группе и канале — только если бот "
                        "администратор. Ничего не меняет.",
         "inputSchema": _OBJ | {"properties": {
             "chat_id": {"type": "integer"}, "limit": {"type": "integer", "default": 20},
             "before": {"type": "integer", "description": "сообщения раньше этого времени (мс Unix)"},
             "after": {"type": "integer", "description": "сообщения позже этого времени (мс Unix)"}},
             "required": ["chat_id"]},
         "fn": list_history},
        {"name": f"{SVC}_get_message",
         "description": "Одно сообщение по id (mid). Ничего не меняет.",
         "inputSchema": _OBJ | {"properties": {"message_id": {"type": "string"}}, "required": ["message_id"]},
         "fn": get_message},
        {"name": f"{SVC}_get_chat",
         "description": "Чат по id: тип (диалог, группа, канал), статус бота в нём (активен, остановлен "
                        "пользователем, удалён), с кем диалог. Ничего не меняет.",
         "inputSchema": _OBJ | {"properties": {"chat_id": {"type": "integer"}}, "required": ["chat_id"]},
         "fn": get_chat},
        {"name": f"{SVC}_get_bot",
         "description": "Проверка ключа: имя и адрес бота, его команды. Ничего не меняет.",
         "inputSchema": _OBJ | {"properties": {}}, "fn": get_bot},
        {"name": f"{SVC}_propose_reply",
         "description": "Черновик ответа клиенту от бота в диалог или чат (не в канал). Сам ничего не отправляет: "
                        "человек подтверждает в пульте, затем max_apply. Заранее проверяет, что бот в чате активен.",
         "inputSchema": _OBJ | {"properties": {
             "chat_id": {"type": "integer"},
             "text": {"type": "string", "description": f"1–{SEND_MAX} символов"},
             "reply_to": {"type": "string", "description": "id сообщения (mid), на которое ответ"}},
             "required": ["chat_id", "text"]},
         "fn": propose_reply},
        {"name": f"{SVC}_apply",
         "description": "Отправить черновик ответа, подтверждённый человеком (id). Без подтверждения и при "
                        "GAS_MAX_WRITE=0 — ошибка.",
         "inputSchema": _OBJ | {"properties": {"id": {"type": "string"}}, "required": ["id"]},
         "fn": apply}],
}

if __name__ == "__main__":
    sys.exit(_core.main(SERVER, SVC))
