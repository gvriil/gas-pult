#!/usr/bin/env python3
"""MCP «browser-local» для пространства (тенанта): stdio JSON-RPC → панель пульта ``/api/bridge/rpc``.

Ставит владелец: ``sudo bin/pult-tenant bridge <slug>`` — копия этого файла в ``config/mcp/bridge_mcp.py`` пространства,
токен пространства рядом (0600, владелец — пользователь пространства), запись в ``config/claude/.claude.json``. Агент
пространства видит только браузеры фокус-ссылок своего пространства: сервер узнаёт пространство по токену
(``Panel.bridge_space``). Секрет владельца (``bridge-local.token``) пространству недоступен — его дом не виден
(ProtectHome службы пространства).

Только стандартная библиотека: файл работает отдельно от пакета gas_pult (пакет лежит в доме владельца).
"""

import json
import os
import sys
import urllib.error
import urllib.request

PANEL = os.environ.get("GAS_PULT_PANEL_URL", "http://127.0.0.1:8765").rstrip("/")
TOKEN_FILE = os.environ.get("GAS_PULT_BRIDGE_TOKEN_FILE", "")


def main() -> int:
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            token = f.read().strip()
    except OSError:
        token = ""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        req = urllib.request.Request(PANEL + "/api/bridge/rpc", json.dumps({"msg": msg}).encode(),
                                     {"Content-Type": "application/json", "X-GP-Space-Token": token})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                out = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            out = {"jsonrpc": "2.0", "id": msg.get("id"),
                   "error": {"code": -32004, "message": f"пульт отказал ({e.code}): мост пространства не настроен"}}
        except Exception as e:                           # панель недоступна — ответ агенту, а не обрыв
            out = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32003, "message": f"пульт: {e}"}}
        if "id" in msg and out.get("jsonrpc"):
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
