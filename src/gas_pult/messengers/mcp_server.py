"""MCP для модели: мессенджер человека — читать свободно, отправить — только черновиком и после «Да» в панели.

Запуск (его пишет в настройки Claude Code панель при подключении):
``python -m gas_pult.messengers.mcp_server <svc>``.
Инструменты: ``<svc>_chats``, ``<svc>_read``, ``<svc>_draft`` (черновик → «Ждут вашего «Да»»), ``<svc>_apply``
(выполнить подтверждённый человеком черновик). Telegram: модель видит только чаты, которые человек открыл ей
в панели — согласие по п. 1.5 условий Telegram даётся на конкретный чат.
"""

from __future__ import annotations

import sys

from gas_pult import messengers as M
from gas_pult.connectors import _core


def _call(svc: str, op: str, **args) -> dict:
    try:
        return M.call(svc, op, **args)
    except (M.BridgeError, M.ConsentRequired, M.NotInstalled) as e:
        raise _core.ToolError(str(e)) from None


def _open(svc: str, chat: str) -> None:
    if svc == "telegram" and str(chat) not in M.allowed(svc):
        raise _core.ToolError("этот чат не открыт модели: человек открывает чаты в панели (Подключения → Telegram → "
                              "«Чаты для модели»), после согласия собеседников")


def server(svc: str) -> dict:
    title = M.TITLES[svc]

    def chats(a: dict):
        got = _call(svc, "chats", limit=int(a.get("limit") or 40)).get("chats") or []
        if svc == "telegram":
            ok = set(M.allowed(svc))
            got = [c for c in got if c["id"] in ok]
            if not got:
                return "модели не открыт ни один чат Telegram — человек открывает их в панели"
        return got

    def read(a: dict):
        chat = str(a.get("chat") or "")
        _open(svc, chat)
        return _call(svc, "messages", chat=chat, limit=int(a.get("limit") or 30)).get("messages") or []

    def draft(a: dict):
        chat, text = str(a.get("chat") or ""), str(a.get("text") or "").strip()
        if not chat or not text:
            raise _core.ToolError("нужны chat и text")
        _open(svc, chat)
        name = str(a.get("name") or chat)[:60]
        return _core.propose(svc, "send", {"chat": chat, "text": text[:4000]},
                             f"Отправить в {title} «{name}»: {text[:300]}")

    def apply(a: dict):
        return _call(svc, "apply", id=str(a.get("id") or ""))

    obj = {"type": "object"}
    return {
        "name": f"gas-pult-{svc}",
        "instructions": (f"{title} человека. Читать можно. Отправить — только {svc}_draft: черновик ждёт «Да» "
                         f"человека в панели; потом {svc}_apply с id. Сам ничего не отправляй и не обещай отправить."),
        "tools": [
            {"name": f"{svc}_chats", "description": f"Чаты {title} (id, имя)", "fn": chats,
             "inputSchema": {**obj, "properties": {"limit": {"type": "integer"}}}},
            {"name": f"{svc}_read", "description": f"Последние сообщения чата {title}", "fn": read,
             "inputSchema": {**obj, "properties": {"chat": {"type": "string"}, "limit": {"type": "integer"}},
                             "required": ["chat"]}},
            {"name": f"{svc}_draft", "description": f"Черновик сообщения в {title} — уйдёт только после «Да» человека",
             "fn": draft, "inputSchema": {**obj, "properties": {"chat": {"type": "string"}, "text": {"type": "string"},
                                                                "name": {"type": "string"}},
                                          "required": ["chat", "text"]}},
            {"name": f"{svc}_apply", "description": "Выполнить черновик, который человек подтвердил «Да» в панели",
             "fn": apply, "inputSchema": {**obj, "properties": {"id": {"type": "string"}}, "required": ["id"]}},
        ],
    }


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in M.SERVICES:
        print("использование: python -m gas_pult.messengers.mcp_server telegram|signal|whatsapp", file=sys.stderr)
        return 2
    _core.serve(server(argv[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
