"""Мост для пространства (владелец 17.11: «да, ставь отдельного пользователя Linux»): pult-tenant bridge кладёт клиент,
токен и хэш; агент пространства по токену видит только браузеры фокус-ссылок своего пространства; агенты владельца —
не видят их, даже если номер окна совпадает (@1 у владельца и @1 в пространстве); откат --off."""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

from test_focus import FX, call, open_link, owner
from test_focus import server as server
from test_focus_browser import connect, rpc
from test_tenants import FakeSystem, enable, lay_of

from gas_pult import tenant_admin, tenants


def setup_space(tmp_path, monkeypatch):
    fs = FakeSystem(monkeypatch)
    lay = lay_of(tmp_path)
    enable(lay.tenants)
    s = tenant_admin.Sys(out=lambda *_: None, runner=fs.runner)
    tenant_admin.create(lay, s, "demo")
    return lay, s


def test_pult_tenant_bridge_files_and_off(tmp_path, monkeypatch):
    lay, s = setup_space(tmp_path, monkeypatch)
    tenant_admin.set_bridge(lay, s, "demo")
    p = tenants.paths("demo", lay.tenants)
    d = p["config"] / "mcp"
    tok = (d / "bridge.token").read_text().strip()
    assert len(tok) > 30 and (d / "bridge.token").stat().st_mode & 0o777 == 0o600
    assert (p["base"] / "bridge.sha256").stat().st_mode & 0o777 == 0o640
    assert "X-GP-Space-Token" in (d / "bridge_mcp.py").read_text()
    srv = json.loads((p["claude"] / ".claude.json").read_text())["mcpServers"]["browser-local"]
    assert srv["args"] == [str(d / "bridge_mcp.py")] and tok not in json.dumps(srv)
    tenant_admin.set_bridge(lay, s, "demo")                                   # повторно — тот же токен
    assert (d / "bridge.token").read_text().strip() == tok
    tenant_admin.bridge_off(lay, s, "demo")
    assert "browser-local" not in json.loads((p["claude"] / ".claude.json").read_text()).get("mcpServers", {})


def test_space_agent_sees_only_its_focus_devices(server, tmp_path, monkeypatch):
    s, p = server, server["p"]
    lay, sysx = setup_space(tmp_path, monkeypatch)
    monkeypatch.setattr(tenants, "root", lambda: lay.tenants)
    tenant_admin.set_bridge(lay, sysx, "demo")
    tok = (tenants.paths("demo", lay.tenants)["config"] / "mcp" / "bridge.token").read_text().strip()
    # фокус-ссылка владельца на его окно @1 с «Браузер» и устройство клиента
    d, _, fc = open_link(s, "@1")
    call(s["base"], "/api/focus/browser", {"id": d["id"], "on": True}, owner(s))
    own_focus = p.devices.claim(call(s["base"], "/api/focus/bridge/pair", {}, fc, FX)[1]["code"], "клиент А", "darwin")
    # фокус-ссылка пространства demo (окно @1 своего tmux — номер совпадает с окном владельца)
    rec = p.focus.new({"id": "@1", "path": "/srv/x", "name": "демо", "space": "demo"}, 1)
    p.focus.set_browser(rec["id"], True)
    space_dev = p.devices.claim(p.devices.pair_code(focus=rec["id"])["code"], "клиент Б", "win32")
    for x in (own_focus, space_dev):
        connect(p, x["id"])

    def space_rpc(token):
        req = urllib.request.Request(s["base"] + "/api/bridge/rpc", json.dumps({"msg": {
            "jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "browser_snapshot"}}}).encode(),
            {"Content-Type": "application/json", "X-GP-Space-Token": token})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return {"http": e.code}

    assert space_rpc(tok)["result"]["dev"] == space_dev["id"]                  # пространство — только своё
    assert space_rpc("чужой-токен".encode().hex())["http"] == 403
    assert rpc(s, "@1")["result"]["dev"] == own_focus["id"]                    # окно владельца @1 — не устройство demo
    p.hub.detach(own_focus["id"], p.hub.conns[own_focus["id"]]["ws"])
    assert rpc(s, "@1")["error"]["code"] == -32000                             # и без своего — чужое не отдаём


def test_client_script_runs_standalone(tmp_path):
    """Клиент пространства работает без пакета gas_pult (дом владельца пространству не виден)."""
    src = tenant_admin.Path(tenant_admin.__file__).with_name("bridge_client.py")
    (tmp_path / "tok").write_text("x")
    env = {"PATH": os.environ["PATH"], "GAS_PULT_PANEL_URL": "http://127.0.0.1:9", "GAS_PULT_BRIDGE_TOKEN_FILE":
           str(tmp_path / "tok")}
    out = subprocess.run([sys.executable, "-I", str(src)], input='{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n',
                         capture_output=True, text=True, env=env, cwd=tmp_path, timeout=30)
    r = json.loads(out.stdout)
    assert r["id"] == 1 and r["error"]["code"] == -32003                      # панели нет — ответ, а не обрыв
