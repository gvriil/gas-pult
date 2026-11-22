"""«Да» — только из панели, сессией человека (штаб 22.11: агент мог обойти «Да» сам).

Агент работает от того же пользователя Linux, что и пульт. Проверяем всё, что ему доступно без панели:
команда ``<svc>_mcp.py confirm`` и ``gas-pult bridge-confirm`` — отказ; своя отметка ``.ok`` рядом с черновиком —
коннектор не выполнит; прямой запрос к панели ``/api/drafts/check`` с секретом владельца — «нет», пока человек не
нажал «Да»; без секрета — 403; «Да» чужим сайтом (Origin) — отказ. После «Да» человека в панели — ровно один раз;
пространство не забирает «Да» владельца и наоборот.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

import pytest
from test_tenant_testers import OWNER, TESTER, call, world  # noqa: F401

from gas_pult import webapp
from gas_pult.connectors import _core, moysklad_mcp

CONF = ".local/state/gas-pult/confirm"


def propose(confirm_dir, summary="Отгрузить заказ №7"):
    old = os.environ.get("GAS_CONFIRM_DIR")
    os.environ["GAS_CONFIRM_DIR"] = str(confirm_dir)
    try:
        return _core.propose("moysklad", "set_order_state", {"id": "7", "state": "отгружен"}, summary)["id"]
    finally:
        os.environ.pop("GAS_CONFIRM_DIR") if old is None else os.environ.__setitem__("GAS_CONFIRM_DIR", old)


def check(base, body, headers):
    req = urllib.request.Request(base + "/api/drafts/check", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


def old_sessions(w):
    from gas_pult import webauth
    a = w["p"].auth
    d = a._load()
    for tok in w["tok"].values():
        if (h := webauth._h(tok)) in d:
            d[h]["created"] = 0
    a._save(d)


@pytest.fixture
def owner_env(world, tmp_path, monkeypatch):  # noqa: F811
    """Коннектор владельца: его папка черновиков, адрес панели и секрет ``bridge-local.token`` (как в жизни)."""
    w = world
    old_sessions(w)
    conf = tmp_path / "owner-confirm"
    tok = tmp_path / "bridge-local.token"
    tok.write_text(webapp.bridge_local_token(w["p"].cfg.data))
    monkeypatch.setenv("GAS_CONFIRM_DIR", str(conf))
    monkeypatch.setenv("GAS_PULT_PANEL_URL", w["base"])
    monkeypatch.setenv("GAS_PULT_LOCAL_TOKEN_FILE", str(tok))
    monkeypatch.delenv("GAS_PULT_BRIDGE_TOKEN_FILE", raising=False)
    return w, conf, tok.read_text()


def test_agent_cannot_confirm_itself(owner_env):
    w, conf, secret = owner_env
    pid = propose(conf)
    # 1) команды подтверждения больше нет
    with pytest.raises(_core.ToolError, match="только кнопкой «Да» в панели"):
        _core.confirm("moysklad", pid)
    r = subprocess.run([sys.executable, moysklad_mcp.__file__, "confirm", pid], capture_output=True, text=True,
                       env={**os.environ}, timeout=30)
    assert r.returncode == 2 and "только кнопкой «Да» в панели" in r.stderr
    # 2) своя отметка на диске — не в счёт
    rec = json.loads((conf / "moysklad" / f"{pid}.json").read_text())
    (conf / "moysklad" / f"{pid}.ok").write_text(rec["digest"])
    with pytest.raises(_core.ToolError, match="нет подтверждения человека"):
        _core.take_confirmed("moysklad", pid, need_flag=False)
    # 3) прямой запрос к панели: с секретом — «нет», без секрета — 403
    assert check(w["base"], {"svc": "moysklad", "id": pid, "digest": rec["digest"]},
                 {"X-GP-Local": secret}) == (200, {"ok": False})
    assert check(w["base"], {"svc": "moysklad", "id": pid, "digest": rec["digest"]}, {})[0] == 403
    assert check(w["base"], {"svc": "moysklad", "id": pid, "digest": rec["digest"]},
                 {"X-GP-Local": "guess-0000"})[0] == 403
    assert (conf / "moysklad" / f"{pid}.json").is_file()                       # не выполнен


def test_human_yes_in_panel_once(owner_env):
    w, conf, _secret = owner_env
    pid = propose(conf)
    code, d = call(w, "/api/drafts/yes", {"svc": "moysklad", "id": pid}, who=OWNER)
    assert code == 200 and d == {"ok": True}, d
    assert not list(conf.rglob("*.ok"))                                        # «Да» не на диске
    rec = _core.take_confirmed("moysklad", pid, need_flag=False)               # коннектор спросил панель
    assert rec["summary"] == "Отгрузить заказ №7"
    pid2 = propose(conf, "Ещё один")
    with pytest.raises(_core.ToolError, match="нет подтверждения человека"):   # «Да» — ровно на тот черновик
        _core.take_confirmed("moysklad", pid2, need_flag=False)


def test_yes_from_foreign_site_refused(owner_env):
    w, conf, _secret = owner_env
    pid = propose(conf)
    from gas_pult import webauth
    req = urllib.request.Request(w["base"] + "/api/drafts/yes", json.dumps({"svc": "moysklad", "id": pid}).encode(),
                                 {"Cookie": f"{webauth.COOKIE}={w['tok'][OWNER]}", "Origin": "https://evil.example"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 400 and "не со страницы панели" in e.value.read().decode()
    with pytest.raises(_core.ToolError):
        _core.take_confirmed("moysklad", pid, need_flag=False)


def test_space_and_owner_yes_do_not_mix(owner_env, tmp_path):
    """«Да» тестировщика пространства забирает только коннектор пространства (его токен моста), не владельца."""
    import hashlib
    w, _conf, secret = owner_env
    demo = w["root"] / "demo/home" / CONF
    pid = propose(demo, "Заказ пространства")
    assert call(w, "/api/drafts/yes", {"svc": "moysklad", "id": pid}, who=TESTER)[0] == 200
    dg = json.loads((demo / "moysklad" / f"{pid}.json").read_text())["digest"]
    # секретом владельца «Да» пространства не забрать
    one = {"svc": "moysklad", "id": pid, "digest": dg}
    assert check(w["base"], one, {"X-GP-Local": secret}) == (200, {"ok": False})
    t = "space-demo-token"
    (w["root"] / "demo" / "bridge.sha256").write_text(hashlib.sha256(t.encode()).hexdigest())
    assert check(w["base"], {"svc": "moysklad", "id": pid, "digest": "чужой"},
                 {"X-GP-Space-Token": t}) == (200, {"ok": False})               # отпечаток не тот — нет
    assert check(w["base"], one, {"X-GP-Space-Token": t}) == (200, {"ok": True})
    assert check(w["base"], one, {"X-GP-Space-Token": t}) == (200, {"ok": False})          # один раз
