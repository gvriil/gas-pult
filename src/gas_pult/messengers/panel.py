"""API панели «Подключения» → «Мессенджеры» (только владелец; пространства — позже, docs/MESSENGERS.md).

Ни один ответ не содержит секретов: ни api_hash, ни кода, ни сессии, ни номера целиком. Ссылка привязки Signal и
WhatsApp уходит в браузер только картинкой QR (PNG data:), сама строка — нет.
"""

from __future__ import annotations

import base64
import json
import sys

from gas_pult import messengers as M
from gas_pult import qr


def _svc(b: dict) -> str:
    svc = str(b.get("svc") or "")
    if svc not in M.SERVICES:
        raise ValueError("нет такого мессенджера")
    return svc


def mcp_config(svc: str) -> dict:
    return {"type": "stdio", "command": sys.executable or "python3",
            "args": ["-m", "gas_pult.messengers.mcp_server", svc],
            "env": {"PYTHONPATH": str(M.SRC), "GAS_MSG_DIR": str(M.root())}}


def ensure_mcp(svc: str, claude=None) -> bool:
    """Подключили — модель получает инструменты: сервер ``msg-<svc>`` в настройках Claude Code владельца (один раз)."""
    mark = M.svc_dir(svc) / "mcp.json"
    if mark.is_file() or not M.account(svc):
        return mark.is_file()
    if claude is None:
        from gas_pult.mcp import _claude as claude
    r = claude("add-json", f"msg-{svc}", json.dumps(mcp_config(svc)), "-s", "user")
    if r.returncode == 0:
        M.write_private(mark, json.dumps({"name": f"msg-{svc}"}))
        return True
    return False


def drop_mcp(svc: str, claude=None) -> None:
    mark = M.svc_dir(svc) / "mcp.json"
    if not mark.is_file():
        return
    if claude is None:
        from gas_pult.mcp import _claude as claude
    claude("remove", f"msg-{svc}", "-s", "user")
    mark.unlink(missing_ok=True)


def qr_data(uri: str) -> str:
    return "data:image/png;base64," + base64.b64encode(qr.png_of(uri, 6)).decode()


def get() -> dict:
    out = M.states()
    for s in out["services"]:
        if s["connected"]:
            s["mcp"] = ensure_mcp(s["id"])
    return out


def post(path: str, b: dict, by) -> dict:
    """``/api/messengers/<что>``: consent, tg/api, tg/login, tg/code, tg/password, link, chats, allow, off."""
    what = path.rsplit("/api/messengers/", 1)[-1]
    svc = "telegram" if what.startswith("tg/") else _svc(b)
    if svc in M.OFF and what != "off" and not (what == "consent" and b.get("accepted") is not True):
        how = next((c["how"] for c in M.CATALOG if c["id"] == svc), "нет официального пути")
        raise ValueError(f"{M.TITLES[svc]} не поддерживается. {how}")   # только «Отключить» и «Отмена»
    if what == "consent":                                  # «Понимаю, подключить» / «Подключить» / «Отмена»
        return M.consent(svc, by, b.get("accepted") is True)
    if what == "off":
        drop_mcp(svc)
        return M.disconnect(svc)
    if not M.consented(svc):
        raise M.ConsentRequired("сначала выбор на экране предупреждения")
    if what == "tg/login":                                 # api_id/api_hash → файл 0600, номер → код в Telegram
        if b.get("api_id") or b.get("api_hash"):
            M.save_tg_api(str(b.get("api_id", "")), str(b.get("api_hash", "")))
            M.stop(svc)                                    # новые ключи — мост перечитает при запуске
        return M.call(svc, "login", phone=str(b.get("phone") or ""))
    if what == "tg/code":
        return M.call(svc, "code", code=str(b.get("code") or ""))
    if what == "tg/password":
        return M.call(svc, "password", password=str(b.get("password") or ""))
    if what == "link":                                     # Signal / WhatsApp: QR картинкой
        r = M.call(svc, "link", timeout=60)
        return {"linked": True} if r.get("linked") else {"qr": qr_data(str(r.get("uri") or ""))}
    if what == "chats":                                    # список для «Чаты для модели» (Telegram)
        got = M.call(svc, "chats", limit=60).get("chats") or []
        return {"chats": [{k: c.get(k) for k in ("id", "name", "kind", "unread")} for c in got],
                "allowed": M.allowed(svc)}
    if what == "allow":
        return {"allowed": M.set_allowed(svc, b.get("chats") or [])}
    raise LookupError("нет такого действия")
