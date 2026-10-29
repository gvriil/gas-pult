import json
import subprocess

import pytest

from gas_pult import mcp


class Fake:
    def __init__(self):
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        out = ("Checking MCP server health…\n\nclaude.ai Docs: https://x - ✔ Connected\n"
               "gh: https://api.githubcopilot.com/mcp/ (HTTP) - ✘ Failed to connect\n")
        return subprocess.CompletedProcess(args, 0, out if args[0] == "list" else "", "")


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(mcp, "_claude", f)
    return f


def test_list_parses_status(fake):
    s = mcp.Mcp().list()
    assert [(x["name"], x["ok"], x["removable"]) for x in s] == [("claude.ai Docs", True, False), ("gh", False, True)]


def test_add_github_puts_token_in_header(fake):
    mcp.Mcp().add("github", "gh", {"token": "github_pat_X"})
    name, cfg = fake.calls[0][1], json.loads(fake.calls[0][2])
    assert fake.calls[0][0] == "add-json" and name == "gh" and fake.calls[0][3:] == ("-s", "user")
    assert cfg == {"type": "http", "url": "https://api.githubcopilot.com/mcp/",
                   "headers": {"Authorization": "Bearer github_pat_X"}}


def test_add_validates(fake):
    with pytest.raises(ValueError, match="Токен"):
        mcp.Mcp().add("github", "gh", {})
    with pytest.raises(ValueError, match="имя"):
        mcp.Mcp().add("context7", "Bad Name", {})
    with pytest.raises(ValueError, match="https"):
        mcp.Mcp().add("http", "x1", {"url": "http://evil.example.com/mcp"})
    assert fake.calls == []


def test_add_stdio_with_env(fake):
    mcp.Mcp().add("stdio", "tool", {"command": "npx -y @scope/srv --flag", "env": "API_KEY=abc\nMODE = fast"})
    cfg = json.loads(fake.calls[0][2])
    assert cfg == {"type": "stdio", "command": "npx", "args": ["-y", "@scope/srv", "--flag"],
                   "env": {"API_KEY": "abc", "MODE": "fast"}}


def test_remove_refuses_foreign(fake):
    with pytest.raises(ValueError):
        mcp.Mcp().remove("claude.ai Docs")


def test_connected_finds_claude_ai_connector(monkeypatch):
    def fake(*args):
        out = ("claude.ai Notion: https://mcp.notion.com/mcp - ✔ Connected\n"
               "notion: https://mcp.notion.com/mcp (HTTP) - ⚠ Needs authentication\n")
        return subprocess.CompletedProcess(args, 0, out, "")
    monkeypatch.setattr(mcp, "_claude", fake)
    s = mcp.Mcp().connected("Notion")
    assert s["name"] == "claude.ai Notion" and s["ok"]
    assert mcp.Mcp().connected("Gmail") is None
