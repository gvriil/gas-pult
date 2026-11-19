"""ВкусВилл (владелец 19.11): официальный MCP-сервер магазина — одной кнопкой, без ключа; OAuth — по желанию."""

import json

from gas_pult import mcp


def test_vkusvill_preset_public_and_oauth(monkeypatch):
    p = next(x for x in mcp.PRESETS if x["id"] == "vkusvill")
    assert p["type"] == "http" and p["url"] == "https://mcp.vkusvill.ru/mcp"
    assert all(f.get("optional") for f in p["fields"])                    # без входа — публичные инструменты
    calls = []

    class R:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(mcp, "_claude", lambda *a, home=None, env=None: calls.append((a, env)) or R())
    m = mcp.Mcp()
    monkeypatch.setattr(m, "list", lambda fresh=False, home=None: [{"name": "vkusvill", "ok": True, "state": ""}])
    m.add("vkusvill", "vkusvill", {})
    cfg = json.loads(calls[0][0][2])
    assert cfg == {"type": "http", "url": "https://mcp.vkusvill.ru/mcp"}
    m.add("vkusvill", "vkusvill", {"client_id": "abc123", "client_secret": "s3cr3t"})
    a, env = calls[-1]
    assert json.loads(a[2])["oauth"] == {"clientId": "abc123"} and "--client-secret" in a
    assert env == {"MCP_CLIENT_SECRET": "s3cr3t"}
