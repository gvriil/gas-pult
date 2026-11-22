"""Мост: установка одной командой, «личные данные не уходят модели», «Да» на сервере перед «Отправить / Оплатить /
Удалить», терминал из белого списка (владелец 21.11). Сервер и логика — здесь; настоящий Mac и Windows не проверены:
скрипт ``install.sh`` проверяется ``bash -n``, ``install.ps1`` — только по тексту (PowerShell на CI нет)."""

import json
import shutil
import subprocess
import urllib.request

import pytest
from test_project_chats import call
from test_project_chats import server as server

from gas_pult import approvals, bridge, bridge_install
from gas_pult.connectors import _core

PANEL = "https://pult.example.org:8443"


# ---------- установщик ----------
def test_install_scripts_check_sha256_no_sudo_and_carry_code():
    sh = bridge_install.script("sh", PANEL, "abcd2345")
    ps = bridge_install.script("ps1", PANEL, "ABCD2345")
    for s in (sh, ps):
        assert "SHASUMS256.txt" in s and "https://nodejs.org/dist/latest-v" in s and "'22'" in s
        assert "sudo" not in s and "RunAs" not in s                                # без прав администратора
        assert f"'{PANEL}'" in s and "'ABCD2345'" in s and "__" not in s.replace("__dirname", "")
        assert bridge_install.EXT_URL in s and "?do=remove" in s                   # расширение и удаление
    assert 'shasum -a 256' in sh and 'sha256sum' in sh and '[ "$GOT" = "$WANT" ]' in sh
    assert "Library/LaunchAgents" in sh and "launchctl bootstrap" in sh
    assert "Get-FileHash -Algorithm SHA256" in ps and "if ($got -ne $want.ToLower())" in ps
    assert "GetFolderPath('Startup')" in ps and "exit" not in ps                # exit закрыл бы окно PowerShell
    rm = bridge_install.script("sh", PANEL, remove=True)
    assert "MODE='remove'" in rm and "CODE=''" in rm
    bad = bridge_install.script("sh", PANEL, "WRONG!!")                         # код не по форме — только сообщение
    assert "устарел" in bad and "curl" not in bad
    if shutil.which("bash"):
        for s in (sh, rm, bad):
            r = subprocess.run(["bash", "-n"], input=s, text=True, capture_output=True)
            assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("url", ["https://x.org';rm -rf ~;'", "https://x.org/path", "javascript:alert(1)",
                                 "https://x .org", 'https://x.org"', "https://x.org:8443$(id)"])
def test_install_panel_address_is_checked(url):
    with pytest.raises(ValueError):
        bridge_install.script("sh", url, "ABCD2345")


def test_commands_for_people():
    c = bridge_install.commands(PANEL, "ABCD2345")
    assert c["mac"] == f"curl -fsSL '{PANEL}/api/bridge/install.sh?c=ABCD2345' | bash"
    assert c["win"] == f"irm '{PANEL}/api/bridge/install.ps1?c=ABCD2345' | iex"
    assert c["mac_remove"].endswith("?do=remove' | bash")


def get(base, path, host=""):
    req = urllib.request.Request(base + path, headers={"Host": host} if host else {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_install_endpoints_one_time_code(server):
    p, base, *_ = server
    code = call(base, "/api/bridge/pair", {}, p.auth.issue(1))[1]["code"]
    st, sh = get(base, f"/api/bridge/install.sh?c={code}")                       # без входа: по коду
    assert st == 200 and f"CODE='{code}'" in sh and f"PANEL='{base}'" in sh
    st, ps = get(base, f"/api/bridge/install.ps1?c={code}")
    assert st == 200 and f"$Code = '{code}'" in ps
    assert p.devices.peek(code)                                                  # скрипт код не тратит
    p.devices.claim(code, "mac", "darwin")
    assert not p.devices.peek(code)
    st, again = get(base, f"/api/bridge/install.sh?c={code}")                    # одноразовый: второй раз — нет
    assert st == 200 and "устарел" in again and "CODE=" not in again
    assert get(base, "/api/bridge/install.sh?do=remove")[1].count("MODE='remove'") == 1
    st, _ = get(base, f"/api/bridge/install.sh?c={code}", host="evil';touch x;'")
    assert st == 400                                                             # чужой Host в скрипт не попадёт
    st, mjs = get(base, "/api/bridge/bridge.mjs")
    assert st == 200 and "run_allowed" in mjs and "process.execPath" in mjs


def test_reinstall_replaces_device_and_new_device_is_private(tmp_path):
    d = bridge.Devices(tmp_path / "dev.json")
    first = d.claim(d.pair_code()["code"], "Мак", "darwin")
    assert d.private(first["id"]) and d.listing()[0]["private"] is True        # по умолчанию — включено
    second = d.claim(d.pair_code()["code"], "Мак", "darwin", old=first["token"])
    assert [x["id"] for x in d.listing()] == [second["id"]]                      # прежняя запись заменена
    third = d.claim(d.pair_code()["code"], "Мак", "darwin", old="чужой-токен")
    assert len(d.listing()) == 2 and d.check(third["token"])
    assert d.set_private(third["id"], False) and not d.private(third["id"])


# ---------- «Личные данные не уходят модели» ----------
def test_mask_pii():
    t = ("Пишите ivan.petrov@mail.ru или +7 (912) 345-67-89, 8 912 345 67 89; карта 4111 1111 1111 1111, "
         "дата 2026-11-21 10:00, заказ №12345, сумма 1 500 ₽")
    m = bridge.mask_pii(t)
    assert "ivan.petrov" not in m and "[почта]" in m
    assert "345-67-89" not in m and "345 67 89" not in m and m.count("[телефон]") == 2
    assert "4111" not in m and "[карта]" in m
    assert "2026-11-21 10:00" in m and "12345" in m and "1 500" in m            # даты и суммы — на месте


SNAP = """### Page
- Page URL: https://mail.example.com/inbox
- Page Title: Входящие — ivan@mail.ru
### Snapshot
```yaml
- banner [ref=e1]:
  - heading "Входящие" [level=1] [ref=e2]
  - searchbox "Поиск в почте" [ref=e3]: пароль от банка
- main [ref=e4]:
  - link "Письмо от Марии: встречаемся у врача в 15:00" [ref=e5] [cursor=pointer]:
    - /url: /msg/1
  - paragraph [ref=e6]: Мой телефон +7 912 345 67 89, номер полиса 123
  - text: Секретный текст письма
  - textbox "Ответ" [ref=e7]: Привет, вот мой адрес
  - button "Отправить" [ref=e8]
  - cell "Иванов Иван" [ref=e9]
```"""


def test_snapshot_keeps_structure_only():
    out = bridge.strip_snapshot(SNAP)
    for keep in ('heading "Входящие" [level=1] [ref=e2]', 'searchbox "Поиск в почте" [ref=e3]',
                 'button "Отправить" [ref=e8]', "- /url: /msg/1", 'textbox "Ответ" [ref=e7]'):
        assert keep in out
    for gone in ("пароль от банка", "+7 912", "Секретный текст", "вот мой адрес", "Иванов", "ivan@mail.ru"):
        assert gone not in out, gone
    assert 'paragraph [ref=e6]: "[текст]"' in out and "[почта]" in out


class FakeWS:
    """Мост-подделка: запоминает, что ушло на компьютер, и сразу отвечает."""

    def __init__(self, hub, did, answer):
        self.hub, self.did, self.answer, self.sent = hub, did, answer, []

    def send_text(self, text):
        m = json.loads(text)
        self.sent.append(m)
        if "id" in m:
            self.hub.on_message(self.did, json.dumps({"jsonrpc": "2.0", "id": m["id"], **self.answer(m)}))

    def close(self, *a):
        pass


def answer(m):
    name = (m.get("params") or {}).get("name")
    if m.get("method") == "tools/list":
        return {"result": {"tools": [{"name": "browser_snapshot"}, {"name": "browser_take_screenshot"},
                                     {"name": "browser_click", "inputSchema": {"type": "object", "properties": {}}},
                                     {"name": "run_allowed"}]}}
    if name == "browser_snapshot":
        return {"result": {"content": [{"type": "text", "text": SNAP}]}}
    if name == "run_allowed":
        return {"result": {"content": [{"type": "text", "text": "Filesystem 100G, admin@corp.com"}]}}
    return {"result": {"content": [{"type": "text", "text": f"ok {name}"}, {"type": "image", "data": "AAAA"}]}}


def hub_with(tmp_path, private=True):
    hub = bridge.Hub(tmp_path / "log.jsonl")
    hub.approve = lambda svc, pid, dg: False                                     # «Да» нет, пока тест не даст
    ws = FakeWS(hub, "d1", answer)
    hub.attach("d1", ws)
    hub.private = lambda did: private
    return hub, ws


def tc(hub, i, name, args=None):
    return hub.call({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name,
                                                                                   "arguments": args or {}}})


def test_private_hides_content_and_forbids_screenshots(tmp_path):
    hub, ws = hub_with(tmp_path)
    tools = [t["name"] for t in hub.call({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]]
    assert "browser_take_screenshot" not in tools and "browser_snapshot" in tools
    shot = tc(hub, 2, "browser_take_screenshot")
    assert shot["error"]["code"] == -32015 and "Личные данные" in shot["error"]["message"]
    assert tc(hub, 3, "screenshot")["error"]["code"] == -32015                    # снимок экрана Мака — тоже
    assert tc(hub, 4, "browser_evaluate", {"function": "() => document.body.innerText"})["error"]["code"] == -32015
    assert len(ws.sent) == 1                                                      # на компьютер ушёл только tools/list
    snap = tc(hub, 5, "browser_snapshot")["result"]["content"][0]["text"]
    assert "Секретный текст" not in snap and "+7 912" not in snap and 'button "Отправить"' in snap
    hover = tc(hub, 6, "browser_hover", {"target": "e2"})["result"]["content"]
    assert [c["type"] for c in hover] == ["text", "text"] and "скрыты" in hover[1]["text"]   # картинки нет
    off, _ = hub_with(tmp_path, private=False)
    assert "Секретный текст" in tc(off, 7, "browser_snapshot")["result"]["content"][0]["text"]


# ---------- «Да» на сервере ----------
def draft_id(out):
    return out["result"]["content"][0]["text"].split("Черновик ", 1)[1].split(":", 1)[0]


def say_yes(approve, pid):
    """«Да» человека в панели (approvals.py): отпечаток черновика — в память службы панели."""
    rec = _core._load(bridge.CONFIRM_SVC, pid)
    approve("", bridge.CONFIRM_SVC, pid, _core._digest(rec["action"], rec["params"]))


def test_send_click_needs_yes_once(tmp_path, monkeypatch):
    ap = approvals.Approvals()                                                   # память службы панели
    monkeypatch.setenv("GAS_CONFIRM_DIR", str(tmp_path / "confirm"))
    hub, ws = hub_with(tmp_path)
    hub.approve = lambda svc, pid, dg: ap.take("", svc, pid, dg)
    tools = hub.call({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    click = next(t for t in tools if t["name"] == "browser_click")
    assert "draft" in click["inputSchema"]["properties"] and "«Да» человека" in click["description"]
    assert tc(hub, 2, "browser_click", {"target": "e5"})["error"]["code"] == -32012   # без снимка — сначала снимок
    tc(hub, 3, "browser_snapshot")
    n = len(ws.sent)
    ok = tc(hub, 4, "browser_click", {"element": "письмо", "target": "e5"})       # обычная ссылка — сразу
    assert "ok browser_click" in ok["result"]["content"][0]["text"] and len(ws.sent) == n + 1
    d = tc(hub, 5, "browser_click", {"element": "кнопка", "target": "e8"})       # «Отправить» — черновик
    text = d["result"]["content"][0]["text"]
    assert "НАЖАТЬ «Отправить» (button)" in text and "mail.example.com/inbox" in text
    assert len(ws.sent) == n + 1                                                  # на компьютер не ушло
    pid = draft_id(d)
    no = tc(hub, 6, "browser_click", {"target": "e8", "draft": pid})
    assert "нет подтверждения" in no["error"]["message"] and len(ws.sent) == n + 1
    assert [x["id"] for x in bridge.drafts()] == [pid]
    say_yes(ap.grant, pid)                                                           # «Да» человека — в панели
    yes = tc(hub, 7, "browser_click", {"target": "e1", "draft": pid})            # агент подменил элемент
    assert "ok browser_click" in yes["result"]["content"][0]["text"]
    assert ws.sent[-1]["params"]["arguments"] == {"element": "кнопка", "target": "e8"}   # из черновика, без draft
    again = tc(hub, 8, "browser_click", {"target": "e8", "draft": pid})
    assert "не найден" in again["error"]["message"] and len(ws.sent) == n + 2   # один раз
    sel = tc(hub, 9, "browser_click", {"element": "Оплатить", "target": "button[type=submit]"})
    assert "НАЖАТЬ «Оплатить» (элемент по селектору)" in sel["result"]["content"][0]["text"]
    form = tc(hub, 10, "browser_type", {"target": "e7", "text": "да", "submit": True})
    assert "отправить форму" in form["result"]["content"][0]["text"]
    search = tc(hub, 11, "browser_type", {"target": "e3", "text": "счёт", "submit": True})
    assert "ok browser_type" in search["result"]["content"][0]["text"]            # Enter в поиске — сразу
    assert "ok" in tc(hub, 12, "browser_press_key", {"key": "Enter"})["result"]["content"][0]["text"]
    assert "Черновик" in tc(hub, 13, "browser_press_key", {"key": "Control+Enter"})["result"]["content"][0]["text"]
    open_hub, open_ws = hub_with(tmp_path, private=False)                        # код на странице — тоже «Да»
    code = tc(open_hub, 14, "browser_run_code", {"code": "page.click('x')"})
    assert "ВЫПОЛНИТЬ КОД" in code["result"]["content"][0]["text"] and not open_ws.sent
    rej = draft_id(tc(hub, 15, "browser_file_upload", {"paths": ["/Users/u/паспорт.pdf"]}))
    assert "ЗАГРУЗИТЬ НА САЙТ" in bridge.drafts()[0]["summary"]
    bridge.reject(rej)
    with pytest.raises(_core.ToolError):
        _core._load(bridge.CONFIRM_SVC, rej)                                      # «Нет» — подтвердить уже нельзя


def test_panel_shows_drafts_and_confirms(server, tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_CONFIRM_DIR", str(tmp_path / "confirm"))
    p, base, *_ = server
    owner = p.auth.issue(1)
    dev = p.devices.claim(p.devices.pair_code()["code"], "Мак мамы", "darwin")
    ws = FakeWS(p.hub, dev["id"], answer)
    p.hub.attach(dev["id"], ws)
    try:
        out = p.hub.call({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "run_allowed", "arguments": {"command": "df -h"}}})
        pid = draft_id(out)
        st, d = call(base, "/api/bridge/drafts", tok=owner)
        assert st == 200 and d["drafts"][0]["id"] == pid and d["drafts"][0]["device_name"] == "Мак мамы"
        assert "df -h" in d["drafts"][0]["summary"] and not d["drafts"][0]["confirmed"]
        assert call(base, "/api/bridge/confirm", {"id": pid}, p.auth.issue(2))[0] == 403   # участнику — нет
        assert call(base, "/api/bridge/confirm", {"id": pid}, owner)[1] == {"ok": True}
        assert call(base, "/api/bridge/drafts", tok=owner)[1]["drafts"][0]["confirmed"] is True
        done = p.hub.call({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": "run_allowed", "arguments": {"command": "rm -rf ~", "draft": pid}}})
        assert ws.sent[-1]["params"]["arguments"] == {"argv": ["df", "-h"], "_confirmed": pid}
        assert "[почта]" in done["result"]["content"][0]["text"]                  # новое устройство — личное
        assert call(base, "/api/bridge/private", {"id": dev["id"], "on": False}, owner)[1] == {"ok": True}
        assert not p.devices.private(dev["id"])
        devs = call(base, "/api/bridge/devices", tok=owner)[1]["devices"]
        assert devs[0]["private"] is False
    finally:
        p.hub.detach(dev["id"], ws)


# ---------- терминал: белый список ----------
@pytest.mark.parametrize("cmd", ["rm -rf ~", "ls; rm -rf ~", "ls | sh", "echo $(id)", "ls `id`", "du -sh ../..",
                                 "du -sh ~/../..", "ls /etc", "open ~/x.command", "open ~/Evil.app", "ping -c 3 -f x",
                                 "ping -c 999 ya.ru", "df", "brew install wget", "ls -R ~", "uptime now",
                                 "ls ~/a > ~/b", "open ~/a.pdf && rm x", "ls ~/'a'", "git status", "sh -c ls",
                                 "ls -la ~/a ~/b", ""])
def test_run_allowed_rejects(cmd):
    with pytest.raises(ValueError):
        bridge.check_command(cmd)


def test_run_allowed_accepts_short_list():
    assert bridge.check_command("df -h") == ["df", "-h"]
    assert bridge.check_command("ls -la ~/Documents") == ["ls", "-la", "~/Documents"]
    assert bridge.check_command("du -sh Downloads") == ["du", "-sh", "Downloads"]
    assert bridge.check_command("open ~/Documents/счёт.pdf") == ["open", "~/Documents/счёт.pdf"]
    assert bridge.check_command("ping -c 3 Ya.Ru") == ["ping", "-c", "3", "ya.ru"]
    assert bridge.check_command("brew list") == ["brew", "list"]
    assert bridge.check_command("uptime") == ["uptime"]


def test_run_allowed_only_after_yes(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_CONFIRM_DIR", str(tmp_path / "confirm"))
    hub, ws = hub_with(tmp_path)
    bad = tc(hub, 1, "run_allowed", {"command": "ls | sh"})
    assert bad["error"]["code"] == -32012 and not ws.sent
    d = tc(hub, 2, "run_allowed", {"command": "du -sh ~/Documents"})
    assert "ВЫПОЛНИТЬ на компьютере команду: du -sh ~/Documents" in d["result"]["content"][0]["text"] and not ws.sent
    fake = tc(hub, 3, "run_allowed", {"command": "df -h", "_confirmed": draft_id(d)})
    assert fake["error"]["code"] == -32012 and not ws.sent


@pytest.mark.skipif(not shutil.which("node"), reason="нужен Node")
def test_bridge_runs_only_confirmed_whitelisted(tmp_path):
    from test_bridge import BRIDGE
    js = (f"import {{ runAllowed }} from {json.dumps(str(BRIDGE))};"
          "const out = [];"
          f"for (const a of [{{argv: ['ls']}}, {{argv: ['sh', '-c', 'id'], _confirmed: 'x'}},"
          f" {{argv: ['ls', '../..'], _confirmed: 'x'}}, {{argv: ['ls', 'a'], _confirmed: 'x'}}])"
          f"  out.push(await runAllowed(a, undefined, {json.dumps(str(tmp_path))}, 'linux')"
          ".catch((e) => 'NO ' + e.message));"
          "console.log(JSON.stringify(out));")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "файл.txt").write_text("x")
    r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=30)
    out = json.loads(r.stdout)
    assert out[0].startswith("NO") and "«Да»" in out[0]                          # без отметки пульта — нет
    assert out[1].startswith("NO") and out[2].startswith("NO")                    # не из списка, «..»
    assert out[3] == "файл.txt"
