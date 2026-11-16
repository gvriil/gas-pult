"""Фокус-ссылка с «Браузер» (владелец 17.11): фокус-пользователь подключает свой компьютер, агент окна этой ссылки
видит только его браузер, агенты других окон — только устройства владельца; отзыв и истечение ссылки гасят
устройство; журнал действий по устройству; без разрешения владельца — нельзя."""

import json
import urllib.request

from test_focus import FX, call, open_link, owner
from test_focus import server as server

from gas_pult import bridge, webapp


class FakeWS:
    """Мост на компьютере: отвечает на любой запрос, помнит, что пришло."""
    def __init__(self, hub, did):
        self.hub, self.did, self.got = hub, did, []

    def send_text(self, text):
        m = json.loads(text)
        self.got.append(m)
        if "id" in m:
            self.hub.on_message(self.did, json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {"dev": self.did}}))

    def close(self, *a):
        pass


def rpc(s, window, msg=None):
    p = s["p"]
    body = json.dumps({"msg": msg or {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": "browser_navigate", "arguments": {"url": "https://example.com"}}},
                       "window": window}).encode()
    req = urllib.request.Request(s["base"] + "/api/bridge/rpc", body, {
        "Content-Type": "application/json", "X-GP-Local": webapp.bridge_local_token(p.cfg.data)})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def connect(p, did):
    ws = FakeWS(p.hub, did)
    p.hub.attach(did, ws)
    return ws


def test_focus_browser_isolation_revoke_and_log(server):
    s, p = server, server["p"]
    d, _, fc = open_link(s, "@1")
    # без разрешения владельца — нельзя
    code, r, _ = call(s["base"], "/api/focus/bridge/pair", {}, fc, FX)
    assert code == 403 and "не разрешил" in r["error"]
    assert call(s["base"], "/api/focus/browser", {"id": d["id"], "on": True}, fc, FX)[0] == 403   # не владельцу
    assert call(s["base"], "/api/focus/browser", {"id": d["id"], "on": True}, owner(s))[1] == {"ok": True}
    assert call(s["base"], "/api/meta", None, fc, FX)[1]["focus"]["browser"] is True
    # фокус-пользователь: код → своё устройство
    code = call(s["base"], "/api/focus/bridge/pair", {}, fc, FX)[1]["code"]
    fdev = p.devices.claim(code, "ноутбук клиента", "darwin")
    assert fdev["focus"] == d["id"]
    odev = p.devices.claim(p.devices.pair_code()["code"], "Мак владельца", "darwin")
    fws, ows = connect(p, fdev["id"]), connect(p, odev["id"])
    # фокус-пользователь видит только своё устройство и не может отозвать чужое
    mine = call(s["base"], "/api/focus/bridge", None, fc, FX)[1]["devices"]
    assert [x["id"] for x in mine] == [fdev["id"]] and mine[0]["online"]
    assert call(s["base"], "/api/focus/bridge/revoke", {"id": odev["id"]}, fc, FX)[0] == 403
    # агент окна ссылки (@1) — только её устройство; агент другого окна (@2) и без окна — только владельца
    assert rpc(s, "@1")["result"]["dev"] == fdev["id"]
    assert rpc(s, "@2")["result"]["dev"] == odev["id"]
    assert rpc(s, "")["result"]["dev"] == odev["id"]
    p.hub.detach(odev["id"], ows)                               # владелец ушёл — окну @2 устройство клиента не отдаём
    assert rpc(s, "@2")["error"]["code"] == -32000
    # владелец видит устройство клиента с пометкой и журнал его действий
    devs = {x["id"]: x for x in call(s["base"], "/api/bridge/devices", None, owner(s))[1]["devices"]}
    assert devs[fdev["id"]]["focus_name"] == d["name"]
    log = call(s["base"], f"/api/bridge/log?id={fdev['id']}", None, owner(s))[1]["log"]
    assert log[0]["tool"] == "browser_navigate" and log[0]["url"] == "https://example.com" and log[0]["ok"]
    assert oct((p.cfg.data / "bridge_log.jsonl").stat().st_mode)[-3:] == "600"
    assert call(s["base"], "/api/bridge/log?id=x", None, fc, FX)[0] == 403        # журнал — только владельцу
    # отзыв ссылки владельцем — устройство клиента больше не работает, хотя мост ещё на связи
    call(s["base"], "/api/focus/revoke", {"id": d["id"]}, owner(s))
    assert not p.bridge_dev_ok(p.devices.get(fdev["id"]))
    assert rpc(s, "@1")["error"]["code"] == -32000
    assert fws.got and all(m.get("method") for m in fws.got)


def test_focus_user_revokes_own_device(server):
    s, p = server, server["p"]
    d, _, fc = open_link(s, "@1")
    call(s["base"], "/api/focus/browser", {"id": d["id"], "on": True}, owner(s))
    fdev = p.devices.claim(call(s["base"], "/api/focus/bridge/pair", {}, fc, FX)[1]["code"], "ноутбук", "win32")
    assert call(s["base"], "/api/focus/bridge/revoke", {"id": fdev["id"]}, fc, FX)[1] == {"ok": True}
    assert p.devices.get(fdev["id"]) is None


def test_journal_keeps_30_days(tmp_path):
    t = [1000.0]
    h = bridge.Hub(tmp_path / "log.jsonl", clock=lambda: t[0])
    msg = {"method": "tools/call", "params": {"name": "browser_snapshot"}}
    h.journal("a", msg, {"result": {}})
    t[0] += bridge.LOG_KEEP + 1
    h.journal("a", msg, {"error": {"message": "нет"}})
    rows = h.history("a")
    assert len(rows) == 1 and rows[0]["ok"] is False and rows[0]["err"] == "нет"
