"""Мост к браузеру пользователя (решение владельца 16.11): пара по коду, WebSocket, прокси MCP, «сохранить на
компьютер», запрет банков и госуслуг по умолчанию, отзыв устройства. Настоящий мост (Node 22+) + подделка MCP."""

import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

import pytest
from test_project_chats import call
from test_project_chats import server as server

from gas_pult import bridge, webapp

BRIDGE = Path(__file__).resolve().parents[1] / "bridge" / "gas-pult-bridge.mjs"


def node_ok() -> bool:
    if not shutil.which("node"):
        return False
    v = subprocess.run(["node", "-p", "process.versions.node.split('.')[0]"], capture_output=True, text=True).stdout
    return v.strip().isdigit() and int(v) >= 22


def test_blocked_hosts_and_pair_codes(tmp_path):
    assert bridge.blocked_host("https://www.gosuslugi.ru/x") == "gosuslugi.ru"
    assert bridge.blocked_host("https://online.sberbank.ru") == "sberbank.ru"
    assert bridge.blocked_host("https://online.sberbank.ru", ["sberbank.ru"]) == ""
    assert bridge.blocked_host("https://example.com") == "" and bridge.blocked_host("javascript:x") == ""
    t = [1000.0]
    d = bridge.Devices(tmp_path / "dev.json", clock=lambda: t[0])
    code = d.pair_code()["code"]
    with pytest.raises(PermissionError):
        d.claim("WRONG123", "mac", "darwin")
    r = d.claim(code, "Мак владельца", "darwin")
    with pytest.raises(PermissionError):
        d.claim(code, "второй раз", "darwin")                                  # код одноразовый
    assert d.check(r["token"])["name"] == "Мак владельца" and d.check("чужой") is None
    assert r["token"] not in (tmp_path / "dev.json").read_text()                # в файле — только хэш
    old = d.pair_code()["code"]
    t[0] += bridge.PAIR_TTL + 1
    with pytest.raises(PermissionError):
        d.claim(old, "mac", "darwin")                                           # 10 минут прошли
    assert d.revoke(r["id"]) and d.check(r["token"]) is None


FAKE_MCP = textwrap.dedent("""
    import json, sys
    for line in sys.stdin:
        m = json.loads(line)
        if "id" not in m:
            continue
        if m.get("method") == "tools/list":
            r = {"tools": [{"name": "browser_navigate"}, {"name": "browser_snapshot"}]}
        else:
            r = {"content": [{"type": "text", "text": "ok " + m.get("params", {}).get("name", m.get("method", ""))}]}
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}), flush=True)
""")


def rpc(base, data, msg):
    req = urllib.request.Request(base + "/api/bridge/rpc", json.dumps({"msg": msg}).encode(),
                                 {"Content-Type": "application/json",
                                  "X-GP-Local": webapp.bridge_local_token(data)})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


@pytest.mark.skipif(not node_ok(), reason="нужен Node 22+")
def test_bridge_end_to_end(server, tmp_path):
    p, base, *_ = server
    home = tmp_path / "user-home"
    home.mkdir()
    fake = tmp_path / "fake_mcp.py"
    fake.write_text(FAKE_MCP)
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home),
           "GAS_PULT_BRIDGE_MCP": f"{sys.executable} {fake}"}
    owner = p.auth.issue(1)
    code = call(base, "/api/bridge/pair", {}, owner)[1]["code"]
    pr = subprocess.Popen(["node", str(BRIDGE), "pair", base, code], env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True)            # run подменён сервером тестов — Popen
    _, err = pr.communicate(timeout=30)
    assert pr.returncode == 0, err
    conf = json.loads((home / ".gas-pult-bridge.json").read_text())
    assert conf["token"] and oct((home / ".gas-pult-bridge.json").stat().st_mode)[-3:] == "600"
    proc = subprocess.Popen(["node", str(BRIDGE)], env=env, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(100):
            if p.hub.online():
                break
            time.sleep(0.1)
        assert p.hub.online() == [conf["id"]], "мост не подключился"
        devs = call(base, "/api/bridge/devices", tok=owner)[1]["devices"]
        assert devs[0]["online"] and devs[0]["id"] == conf["id"]
        tools = rpc(base, p.cfg.data, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert tools["id"] == 1 and [t["name"] for t in tools["result"]["tools"]] == [
            "browser_navigate", "browser_snapshot", "save_to_computer"]
        ok = rpc(base, p.cfg.data, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                    "params": {"name": "browser_snapshot", "arguments": {}}})
        assert ok["result"]["content"][0]["text"] == "ok browser_snapshot"
        bad = rpc(base, p.cfg.data, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "browser_navigate", "arguments": {"url": "https://www.gosuslugi.ru/"}}})
        assert bad["error"]["code"] == -32001 and "gosuslugi.ru" in bad["error"]["message"]
        sv = rpc(base, p.cfg.data, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "save_to_computer", "arguments": {"name": "отчёт.txt", "content": "привет"}}})
        saved = home / "Downloads" / "отчёт.txt"
        assert "Сохранено" in sv["result"]["content"][0]["text"] and saved.read_text() == "привет"
        rpc(base, p.cfg.data, {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
            "name": "save_to_computer", "arguments": {"name": "отчёт.txt", "content": "второй"}}})
        assert (home / "Downloads" / "отчёт-2.txt").read_text() == "второй"         # не перезаписывает
        assert call(base, "/api/bridge/revoke", {"id": conf["id"]}, owner)[1] == {"ok": True}
        assert call(base, "/api/bridge/devices", tok=owner)[1]["devices"] == []
    finally:
        proc.terminate()
        proc.wait(5)


def test_rpc_needs_local_secret_and_owner_routes(server):
    p, base, *_ = server
    req = urllib.request.Request(base + "/api/bridge/rpc", b'{"msg": {}}', {"Content-Type": "application/json",
                                                                         "X-GP-Local": "wrong-secret"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 403
    assert call(base, "/api/bridge/pair", {}, p.auth.issue(2))[0] == 403          # участнику — нет
    nobody = rpc(base, p.cfg.data, {"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
    assert nobody["error"]["code"] == -32000 and "не подключён" in nobody["error"]["message"]


def test_bridge_code_endpoint(server):
    p, base, *_ = server
    hdr = {"Content-Type": "application/json", "X-GP-Local": webapp.bridge_local_token(p.cfg.data)}
    req = urllib.request.Request(base + "/api/bridge/code", b"{}", hdr)
    with urllib.request.urlopen(req, timeout=10) as r:
        code = json.loads(r.read())["code"]
    assert p.devices.claim(code, "mac", "darwin")["token"]
