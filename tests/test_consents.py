"""Согласие перед подключением (владелец 23.11, consents.py): «аккаунт мой, ответственность моя».

Без записи согласия на это подключение и текущую версию текста подключение отвечает 409 ``code=consent``; запись —
кто, что, когда, версия, только добавлением, файл 0600. Фокус-ссылка не видит ресурсов владельца. Поиск каталога —
по названию и назначению (js/connections.js, в node). Живой tmux и настоящий claude не запускаются."""

import json
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import access, consents, focus, mcp, webapp, webauth
from gas_pult.config import Config

OWNER, MEMBER, VIEWER = 1001, 1002, 1003
WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"


def call(base, path, body=None, token="", focus_cookie=""):
    hdr = {"Content-Type": "application/json", "Cookie": f"{webauth.COOKIE}={token}"}
    if focus_cookie:
        hdr = {"Content-Type": "application/json", "Cookie": f"{focus.COOKIE}={focus_cookie}", focus.HEADER: "1"}
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, hdr)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


@pytest.fixture
def srv(monkeypatch, tmp_path):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    p = webapp.Panel(Config(token="1:T", owners=[OWNER]))
    p.people.add(MEMBER, "member", "Участник")
    p.people.add(VIEWER, "viewer", "Наблюдатель")
    for uid in (OWNER, MEMBER, VIEWER):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    calls = []
    owner_servers = [{"name": "claude.ai Gmail", "target": "x", "ok": True, "state": "", "removable": False},
                     {"name": "owner-crm", "target": "x", "ok": True, "state": "", "removable": True}]
    monkeypatch.setattr(p.mcp, "list", lambda fresh=False, home=None: calls.append(("list", home)) or owner_servers)
    monkeypatch.setattr(p.mcp, "add", lambda preset, name, values, home=None: calls.append(("add", preset)) or "ok")
    monkeypatch.setattr(p.mcp, "connected", lambda match, home=None: calls.append(("connected", match))
                        or {"ok": True, "state": "on"})
    monkeypatch.setattr(p, "set_key", lambda provider, key: calls.append(("key", provider)) or {"checked": True})
    links = {"fc1": {"id": "f1", "w": "@5", "name": "Фокус", "space": None, "by": OWNER},
             "fc2": {"id": "f2", "w": "@6", "name": "Пространство", "space": "alpha", "by": OWNER}}
    monkeypatch.setattr(p, "focus_rec", lambda c: links[c] if c in links else (_ for _ in ()).throw(focus.Gone("нет")))
    s = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield {"base": f"http://127.0.0.1:{s.server_address[1]}", "p": p, "calls": calls, "data": tmp_path,
           "owner": p.auth.issue(OWNER), "member": p.auth.issue(MEMBER), "viewer": p.auth.issue(VIEWER)}
    s.shutdown()


def test_record_is_append_only_versioned_and_private(tmp_path, monkeypatch):
    f = consents.path_of(tmp_path)
    with pytest.raises(consents.Needed):
        consents.require(f, "uid:7", "mcp:github")
    r = consents.record(f, "uid:7", "mcp:github", "GitHub", clock=lambda: 100)
    assert r == {"what": "mcp:github", "title": "GitHub", "v": consents.CONSENT_V, "at": 100}
    consents.require(f, "uid:7", "mcp:github")
    assert consents.record(f, "uid:7", "mcp:github", clock=lambda: 200)["at"] == 100   # уже есть — второй раз не пишем
    assert f.stat().st_mode & 0o777 == 0o600
    with pytest.raises(consents.Needed):                                   # чужое согласие не считается
        consents.require(f, "uid:8", "mcp:github")
    monkeypatch.setattr(consents, "CONSENT_V", "2099-01-01")              # новый текст — спросить заново
    with pytest.raises(consents.Needed):
        consents.require(f, "uid:7", "mcp:github")
    consents.record(f, "uid:7", "mcp:github", clock=lambda: 300)
    log = consents.listing(f, "uid:7")
    assert [x["v"] for x in log] == [r["v"], "2099-01-01"]                 # старая запись осталась
    for bad in ("", "mcp:", "shell:rm", "mcp:../x", "key:A B"):
        with pytest.raises(ValueError):
            consents.check_what(bad)


def test_without_checkbox_409_then_saved_with_version(srv):
    b, c = srv["base"], srv["calls"]
    code, d = call(b, "/api/mcp/add", {"preset": "context7", "name": "ctx"}, srv["member"])
    assert code == 409 and d["code"] == "consent" and d["what"] == "mcp:context7" and d["v"] == consents.CONSENT_V
    assert ("add", "context7") not in c                                     # без согласия ничего не подключено
    assert call(b, "/api/consent", {"what": "mcp:context7"}, srv["member"])[0] == 400   # галочка не отмечена
    code, d = call(b, "/api/consent", {"what": "mcp:context7", "title": "Context7", "accepted": True}, srv["member"])
    assert code == 200 and d["consent"]["v"] == consents.CONSENT_V and d["consent"]["what"] == "mcp:context7"
    code, d = call(b, "/api/consent", None, srv["member"])
    assert code == 200 and "mcp:context7" in d["given"] and d["check"] == consents.CHECK and d["points"]
    assert call(b, "/api/mcp/add", {"preset": "context7", "name": "ctx"}, srv["member"])[0] == 200
    rec = json.loads((srv["data"] / "consents.json").read_text())
    assert rec[f"uid:{MEMBER}"][0]["what"] == "mcp:context7" and rec[f"uid:{MEMBER}"][0]["at"] > 0
    assert call(b, "/api/consent", None, srv["owner"])[1]["given"] == []   # у каждого — своё
    assert call(b, "/api/consent", {"what": "mcp:x", "accepted": True}, srv["viewer"])[0] == 403
    assert "/api/consent" in access.V1_NEVER


def test_version_change_asks_again(srv, monkeypatch):
    b = srv["base"]
    call(b, "/api/consent", {"what": "mcp:context7", "accepted": True}, srv["member"])
    assert call(b, "/api/mcp/add", {"preset": "context7", "name": "ctx"}, srv["member"])[0] == 200
    monkeypatch.setattr(consents, "CONSENT_V", "2099-01-01")
    assert call(b, "/api/mcp/add", {"preset": "context7", "name": "ctx"}, srv["member"])[0] == 409
    assert call(b, "/api/consent", None, srv["member"])[1]["given"] == []


def test_model_key_and_messenger_need_consent(srv):
    b, c = srv["base"], srv["calls"]
    code, d = call(b, "/api/keys", {"provider": "openrouter", "key": "test-key-0123456789abcdef"}, srv["owner"])
    assert code == 409 and d["what"] == "key:openrouter" and ("key", "openrouter") not in c
    assert call(b, "/api/openrouter/start", {}, srv["owner"])[0] == 409
    call(b, "/api/consent", {"what": "key:openrouter", "accepted": True}, srv["owner"])
    assert call(b, "/api/keys", {"provider": "openrouter", "key": "test-key-0123456789abcdef"}, srv["owner"])[0] == 200
    assert call(b, "/api/keys", {"provider": "nope", "key": "x"}, srv["owner"])[0] != 409   # неизвестный — set_key
    code, d = call(b, "/api/messengers/consent", {"svc": "telegram", "accepted": True}, srv["owner"])
    assert code == 409 and d["what"] == "messenger:telegram"
    code, d = call(b, "/api/messengers/consent", {"svc": "whatsapp", "accepted": True}, srv["owner"])
    assert code == 400 and "запрещено правилами WhatsApp" in d["error"]


def test_focus_link_sees_no_owner_resources(srv):
    b, c = srv["base"], srv["calls"]
    code, d = call(b, "/api/mcp", focus_cookie="fc1")
    assert code == 200 and d["focus"] and d["servers"] == [] and d["presets"] == [] and d["connectors"] == []
    assert not any(x.get("owner") for x in d["cards"]) and {x["id"] for x in d["cards"]} >= {"whatsapp", "openai"}
    text = json.dumps(d, ensure_ascii=False)
    for owner_thing in ("Gmail", "owner-crm", "rclone", "find_in_docs", "my.telegram.org", "пароль приложения"):
        assert owner_thing not in text, owner_thing
    assert not any(x[0] == "list" for x in c)                              # серверы владельца даже не спрашивали
    code, d = call(b, "/api/mcp/connected?id=gmail", focus_cookie="fc1")
    assert code == 200 and d == {"found": False, "ok": False, "state": ""} and not any(x[0] == "connected" for x in c)
    assert call(b, "/api/mcp/add", {"preset": "github", "name": "gh"}, focus_cookie="fc1")[0] == 403
    for path in ("/api/keys", "/api/messengers", "/api/calendars/keys", "/api/providers"):
        assert call(b, path, focus_cookie="fc1")[0] == 403, path
    # согласие по ссылке — за её пространством (или самой ссылкой), не за владельцем
    assert call(b, "/api/consent", {"what": "mcp:github", "accepted": True}, focus_cookie="fc2")[0] == 200
    assert call(b, "/api/consent", {"what": "mcp:notion", "accepted": True}, focus_cookie="fc1")[0] == 200
    rec = json.loads((srv["data"] / "consents.json").read_text())
    assert set(rec) == {"space:alpha", "focus:f1"} and f"uid:{OWNER}" not in rec
    owner = call(b, "/api/mcp", None, srv["owner"])[1]                     # владельцу — как раньше, со своим
    assert {"owner-crm", "claude.ai Gmail"} <= {s["name"] for s in owner["servers"]}
    assert any(x.get("owner") for x in owner["cards"])
    member = call(b, "/api/mcp", None, srv["member"])[1]
    assert not any(x.get("owner") for x in member["cards"]) and "stdio" not in {p["id"] for p in member["presets"]}


def test_catalog_only_does_not_poll_servers(srv):
    code, d = call(srv["base"], "/api/mcp?catalog=1", None, srv["member"])
    assert code == 200 and d["servers"] is None and d["presets"] and not srv["calls"]
    assert [x["id"] for x in d["cats"]] == ["ai", "messengers", "mail", "docs", "research", "other"]


def test_catalog_categories_elicit_and_service_rules():
    cats = {c["id"] for c in mcp.CATS}
    assert all(x["cat"] in cats for x in mcp.PRESETS + mcp.CONNECTORS + mcp.CARDS)
    el = next(p for p in mcp.PRESETS if p["id"] == "elicit")
    assert el["cat"] == "research" and el["url"] == "https://elicit.com/api/mcp" and el["type"] == "http"
    assert "Pro, Scale и Enterprise" in el["about"] and "OAuth 2.0" in el["after"] and not el["fields"]
    cards = {c["id"]: c for c in mcp.CARDS}
    assert cards["whatsapp"]["state"] == "off" and "запрещено правилами WhatsApp" in cards["whatsapp"]["about"]
    assert "Cloud API" in cards["whatsapp-business"]["about"]
    assert cards["max"]["state"] == "off" and "Нет официального пути" in cards["max"]["about"]
    assert "my.telegram.org" in cards["telegram"]["about"]
    assert "Логин и пароль ChatGPT пульт не принимает" in cards["openai"]["about"]


def test_search_by_purpose_in_node(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("нет node")
    js = (WEB / "js/connections.js").read_text(encoding="utf-8")
    (tmp_path / "c.mjs").write_text(js, encoding="utf-8")
    items = [{"id": p["id"], "title": p["title"], "about": p["about"], "cat": p["cat"]} for p in mcp.PRESETS]
    items += [{"id": c["id"], "title": c["title"], "about": c["about"], "cat": c["cat"]} for c in mcp.CONNECTORS]
    titles = json.dumps({c["id"]: c["title"] for c in mcp.CATS}, ensure_ascii=False)
    out = subprocess.run([node, "--input-type=module", "-e",
                          f"import * as C from '{tmp_path / 'c.mjs'}';"
                          f"const L = {json.dumps(items, ensure_ascii=False)}, T = {titles};"
                          "for (const q of ['научные статьи', 'умный дом', 'ПОЧТА', 'исследования', 'Elicit',"
                          " 'zzz qq'])"
                          " console.log(q + '=' + C.pick(L, q, (c) => T[c]).map((x) => x.id).join(','));"],
                         capture_output=True, text=True, timeout=20)
    got = dict(x.split("=", 1) for x in out.stdout.splitlines())
    assert got["научные статьи"] == "elicit"                               # по назначению, не по названию
    assert got["умный дом"] == "homeassistant"
    assert "gmail" in got["ПОЧТА"].split(",")
    assert set(got["исследования"].split(",")) >= {"elicit", "websearch", "context7"}   # по разделу
    assert got["Elicit"] == "elicit" and got["zzz qq"] == ""


def test_consent_sheet_wired_before_every_connection():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert page.count("await consentOk(") >= 3                             # MCP, коннектор claude.ai, ключ голоса
    for part, what in (("profile", '"key:" + p.id'), ("calkeys", '"calendar:" + kind'), ("spacemcp", '"mcp:" + p.id'),
                       ("messengers", '"messenger:" + svc')):
        assert what in (WEB / f"js/{part}.js").read_text(encoding="utf-8"), part
    js = (WEB / "js/connections.js").read_text(encoding="utf-8")
    assert "data-ok disabled" in js and "ok.disabled = !box.checked" in js   # без галочки «Подключить» неактивна
