"""Интеграции на чат (владелец 19.11): выключенные — флагом --disallowedTools mcp__<сервер>; набор живёт у разговора,
перезапуск его сохраняет; посреди чата — только владелец и админ."""

import shlex

from gas_pult import chatmcp, webapp


def test_prefix_and_flags(tmp_path):
    assert chatmcp.prefix("claude.ai Gmail") == "mcp__claude_ai_Gmail"
    assert chatmcp.prefix("plugin:telegram:telegram") == "mcp__plugin_telegram_telegram"
    assert chatmcp.prefix("websearch") == "mcp__websearch"
    f = chatmcp.flags(["claude.ai Gmail", "claude.ai Gmail", "websearch"])
    assert shlex.split(f) == ["--disallowedTools", "mcp__claude_ai_Gmail mcp__websearch"]
    assert chatmcp.flags([]) == "" and chatmcp.flags(None) == ""


def test_store_per_conversation(tmp_path):
    p = tmp_path / "chat-mcp.json"
    assert chatmcp.put(p, "s1", ["claude.ai Gmail"]) == ["claude.ai Gmail"]
    assert chatmcp.get(p, "s1") == ["claude.ai Gmail"] and chatmcp.get(p, "s2") == []
    assert (p.stat().st_mode & 0o777) == 0o600
    chatmcp.put(p, "s1", [])
    assert chatmcp.get(p, "s1") == [] and "s1" not in p.read_text()


def test_chat_mcp_owner_and_admin_only():
    assert "/api/chat/mcp" in webapp.OWNER_ONLY and "/api/chat/mcp" in webapp.ADMIN_OK
    assert "/api/chat/mcp" not in webapp.FOCUS_POST and "/api/chat/mcp" not in webapp.SPACE_OK


def test_toggles_in_new_chat_and_open_chat():
    from pathlib import Path
    web = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
    nc = (web / "js/newchat.js").read_text(encoding="utf-8")
    assert "mcp_off: off" in nc and 'store("lastMcpOff"' in nc and "function mcpMenu" in nc
    assert '"/api/chat/mcp"' in nc and "через 5 с" in nc and "Отменить" in nc
    page = (web / "index.html").read_text(encoding="utf-8")
    assert 'label: "Интеграции чата"' in page and 'm.chatMcp(s)' in page
