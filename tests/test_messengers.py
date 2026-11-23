"""Мессенджеры «как пользователь» (messengers/): выбор человека обязателен, отправка — только черновиком после «Да»,
секреты — 0600 и не в ответах API, мост спит по простою. Без сети: подделки вместо Telethon, signal-cli и Node."""

import asyncio
import contextlib
import json
import os
import stat
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import pytest

from gas_pult import brief
from gas_pult import messengers as M
from gas_pult.connectors import _core
from gas_pult.messengers import host as H
from gas_pult.messengers import mcp_server, panel


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    monkeypatch.delenv("GAS_MSG_DIR", raising=False)          # корень — папка данных пульта из conftest (короткий путь)
    monkeypatch.setenv("GAS_CONFIRM_DIR", str(tmp_path / "confirm"))
    for k in ("GAS_MSG_TELETHON_PY", "GAS_MSG_SIGNAL_CLI", "GAS_MSG_NODE"):
        monkeypatch.delenv(k, raising=False)


def mode(p) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


# ---------- выбор человека: без него мост не стартует ----------
def test_bridge_does_not_start_without_choice():
    for svc in M.SERVICES:
        with pytest.raises(M.ConsentRequired):
            M.spawn(svc)
        assert H.main([svc]) == 3                    # второй замок — в самом процессе моста
    with pytest.raises(M.ConsentRequired):
        panel.post("/api/messengers/tg/login", {"phone": "+79990000000"}, 1)
    with pytest.raises(M.ConsentRequired):
        panel.post("/api/messengers/link", {"svc": "signal"}, 1)


def test_personal_whatsapp_not_supported_only_off():
    """Личный WhatsApp через неофициальный клиент — запрещено правилами WhatsApp (владелец 23.11): не подключается,
    уже подключённый — только «Отключить» и «Отмена»."""
    assert next(c for c in M.CATALOG if c["id"] == "whatsapp")["kind"] == "off"
    for path, b in (("/api/messengers/consent", {"svc": "whatsapp", "accepted": True}),
                    ("/api/messengers/link", {"svc": "whatsapp"})):
        with pytest.raises(ValueError, match="запрещено правилами WhatsApp"):
            panel.post(path, b, 1)
    assert panel.post("/api/messengers/consent", {"svc": "whatsapp", "accepted": False}, 1)["consented"] is False


def test_choice_is_recorded_with_time_and_who_and_cancel_removes_it():
    r = M.consent("whatsapp", 42, True)
    assert r["consented"] and r["at"]
    f = M.svc_dir("whatsapp") / "consent.json"
    rec = json.loads(f.read_text())
    assert rec["by"] == "42" and rec["at"] and "Неофициальный способ" in rec["text"] and "Решаете вы" in rec["text"]
    assert mode(f) == 0o600 and mode(f.parent) == 0o700
    assert M.consented("whatsapp")
    M.consent("whatsapp", 42, False)                 # «Отмена»
    assert not f.exists() and not M.consented("whatsapp")


def test_telegram_choice_text_names_clause_1_5():
    assert "п. 1.5" in M.CONSENT_TEXT["telegram"] and "согласие собеседников" in M.CONSENT_TEXT["telegram"]
    for svc in ("signal", "whatsapp"):
        t = M.CONSENT_TEXT[svc]
        assert t.startswith("Неофициальный способ.") and "заблокировать" in t and "отдельный номер" in t


def test_max_is_only_a_line():
    mx = next(c for c in M.CATALOG if c["id"] == "max")
    assert mx["kind"] == "off" and "бот организации" in mx["about"] and "max" not in M.SERVICES


# ---------- секреты: 0600, не в ответах ----------
HASH = "0123456789abcdef0123456789abcdef"


def test_secrets_are_private_and_never_in_api():
    M.consent("telegram", 1, True)
    M.save_tg_api("1234567", HASH)
    f = M.svc_dir("telegram") / "api.json"
    assert mode(f) == 0o600
    M.write_private(M.svc_dir("telegram") / "account.json",
                    json.dumps({"connected": True, "who": M.mask("+79991234567")}))
    M.consent("signal", 1, True)
    M.write_private(M.svc_dir("signal") / "account.json",
                    json.dumps({"connected": True, "who": M.mask("+4915112345678"), "number": "+4915112345678"}))
    calls = []
    out = json.dumps(_get(calls), ensure_ascii=False)
    assert calls and calls[0][:2] == ("add-json", "msg-telegram")      # подключили — модель получила инструменты
    for secret in (HASH, "1234567", "+79991234567", "79991234567", "+4915112345678"):
        assert secret not in out
    assert "*** 4567" in out


def _get(calls):
    def fake_claude(*a):
        calls.append(a)
        return type("R", (), {"returncode": 0})()
    import gas_pult.mcp
    old, gas_pult.mcp._claude = gas_pult.mcp._claude, fake_claude
    try:
        return panel.get()
    finally:
        gas_pult.mcp._claude = old


def test_bad_telegram_keys_rejected():
    with pytest.raises(ValueError):
        M.save_tg_api("abc", HASH)
    with pytest.raises(ValueError):
        M.save_tg_api("123456", "not-a-hash")


def test_link_returns_only_qr_picture(monkeypatch):
    M.consent("signal", 1, True)
    uri = "sgnl://linkdevice?uuid=AbCdEfGhIjKlMnOpQrStUv&pub_key=" + "A" * 44
    monkeypatch.setattr(M, "call", lambda svc, op, **k: {"uri": uri})
    r = panel.post("/api/messengers/link", {"svc": "signal"}, 1)
    assert r["qr"].startswith("data:image/png;base64,") and uri not in json.dumps(r)


def test_whatsapp_qr_fits():
    """Строка QR WhatsApp — ~280 знаков (замер 22.11): QR панели теперь до версии 15 (412 байт)."""
    from gas_pult import qr
    assert len(qr.encode("2@" + "x" * 275)) == 12 * 4 + 17          # версия 12


def test_need_install_shows_command(monkeypatch, tmp_path):
    monkeypatch.setattr(M.shutil, "which", lambda name: None)
    monkeypatch.setattr(M.importlib.util, "find_spec", lambda name: None)
    assert "pip install telethon==" in M.need_install("telegram")["cmd"]
    assert "signal-cli" in M.need_install("signal")["cmd"]
    assert M.need_install("whatsapp")["what"].startswith("Node")
    monkeypatch.setenv("GAS_MSG_NODE", "/usr/bin/true")
    assert "@whiskeysockets/baileys@" in M.need_install("whatsapp")["cmd"]
    M.consent("signal", 1, True)
    with pytest.raises(M.NotInstalled):
        M.spawn("signal")


# ---------- мост: сокет 0600, сон по простою, отправка только черновиком ----------
class Fake:
    OPS = ("status", "inbox")

    def __init__(self):
        self.sent, self.stopped = [], False

    async def start(self):
        pass

    async def stop(self):
        self.stopped = True

    async def status(self):
        return {"ok": True}

    async def inbox(self, since=0):
        return {"items": [{"chat": "1", "text": "привет", "ts": 1}]}

    async def send(self, params):
        self.sent.append(params)
        return {"ok": True, "sent": True}


async def ask(sock, req):
    r, w = await asyncio.open_unix_connection(str(sock))
    w.write((json.dumps(req) + "\n").encode())
    await w.drain()
    out = json.loads(await r.readline())
    w.close()
    return out


def test_host_sleeps_when_idle_and_socket_is_private():
    M.consent("telegram", 1, True)
    d, fake = M.svc_dir("telegram"), Fake()
    host = H.Host("telegram", d, fake, idle=0.4, tick=0.05)

    async def go():
        task = asyncio.ensure_future(host.run())
        for _ in range(50):
            if (d / "host.sock").exists():
                break
            await asyncio.sleep(0.02)
        assert mode(d / "host.sock") == 0o600
        assert (await ask(d / "host.sock", {"op": "ping"}))["ok"]
        assert (await ask(d / "host.sock", {"op": "inbox"}))["items"][0]["text"] == "привет"
        for _ in range(4):                            # «жив?» из панели — не работа: сну не мешает
            await asyncio.sleep(0.15)
            if not task.done():
                with contextlib.suppress(OSError):  # мост мог уснуть между проверкой и запросом
                    await ask(d / "host.sock", {"op": "ping"})
        await asyncio.wait_for(task, 3)               # никто не спрашивает — мост выключился сам
    asyncio.run(go())
    assert not (d / "host.sock").exists() and fake.stopped


def test_send_only_through_confirmed_draft(tmp_path, monkeypatch):
    import panel_stub  # «Да» человека — в памяти службы панели (approvals.py, #421)
    for k, v in panel_stub.env(tmp_path).items():
        if k != "GAS_CONFIRM_DIR":
            monkeypatch.setenv(k, v)
    M.consent("whatsapp", 1, True)
    d, fake = M.svc_dir("whatsapp"), Fake()
    host = H.Host("whatsapp", d, fake, idle=30, tick=0.05)

    async def go():
        assert "нет такой операции" in (await host_call(host, {"op": "send", "chat": "1", "text": "x"}))["error"]
        pid = _core.propose("whatsapp", "send", {"chat": "1", "text": "Привет"}, "Отправить")["id"]
        assert "нет подтверждения" in (await host_call(host, {"op": "apply", "id": pid}))["error"]
        panel_stub.grant("whatsapp", pid)             # «Да» в панели (команды confirm больше нет)
        assert (await host_call(host, {"op": "apply", "id": pid}))["sent"]
        assert "не найден" in (await host_call(host, {"op": "apply", "id": pid}))["error"]   # один раз
    asyncio.run(go())
    assert fake.sent == [{"chat": "1", "text": "Привет"}]


async def host_call(host, req):
    class W:
        def __init__(self):
            self.buf = b""

        def write(self, b):
            self.buf += b

        async def drain(self):
            pass

        def close(self):
            pass
    r = asyncio.StreamReader()
    r.feed_data((json.dumps(req) + "\n").encode())
    r.feed_eof()
    w = W()
    await host.client(r, w)
    return json.loads(w.buf)


# ---------- модель: читает только открытые чаты Telegram, отправить — только черновик ----------
def tool(svc, name):
    return next(t for t in mcp_server.server(svc)["tools"] if t["name"] == f"{svc}_{name}")


def test_mcp_has_no_direct_send_and_draft_goes_to_yes(monkeypatch):
    names = {t["name"] for t in mcp_server.server("whatsapp")["tools"]}
    assert names == {"whatsapp_chats", "whatsapp_read", "whatsapp_draft", "whatsapp_apply"}
    r = tool("whatsapp", "draft")["fn"]({"chat": "49151@s.whatsapp.net", "text": "Буду в 7", "name": "Анна"})
    assert "ждёт подтверждения" in r["status"]
    f = _core._dir("whatsapp") / f"{r['id']}.json"
    assert mode(f) == 0o600 and "Анна" in json.loads(f.read_text())["summary"]


def test_telegram_model_sees_only_allowed_chats(monkeypatch):
    M.consent("telegram", 1, True)
    chats = [{"id": "1", "name": "Анна"}, {"id": "2", "name": "B"}]
    monkeypatch.setattr(M, "call", lambda svc, op, **k: {"chats": chats, "messages": [{"text": "x"}]})
    assert "не открыт" in tool("telegram", "chats")["fn"]({})
    with pytest.raises(_core.ToolError):
        tool("telegram", "read")["fn"]({"chat": "2"})
    with pytest.raises(_core.ToolError):
        tool("telegram", "draft")["fn"]({"chat": "2", "text": "hi"})
    M.set_allowed("telegram", ["1"])
    assert [c["id"] for c in tool("telegram", "chats")["fn"]({})] == ["1"]
    assert tool("telegram", "read")["fn"]({"chat": "1"}) == [{"text": "x"}]
    assert mode(M.svc_dir("telegram") / "allowed.json") == 0o600


# ---------- подделки внешних программ: signal-cli и Node ----------
def fake_exe(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    p.chmod(0o755)
    return str(p)


def test_signal_link_and_receive_with_fake_cli(tmp_path):
    from gas_pult.messengers.signal_cli import Signal
    cli = fake_exe(tmp_path, "signal-cli", """
        import json, sys
        a = sys.argv
        if "link" in a:
            print("sgnl://linkdevice?uuid=abc&pub_key=def", flush=True)
            print("Associated with: +4915112345678", flush=True)
        elif "receive" in a:
            print(json.dumps({"envelope": {"sourceNumber": "+4917", "sourceName": "Анна", "timestamp": 1700000000000,
                                           "dataMessage": {"message": "Привет"}}}))
        elif "send" in a:
            open(sys.argv[0] + ".sent", "w").write(json.dumps(a[a.index("send"):]))
    """)
    M.consent("signal", 1, True)
    d = M.svc_dir("signal")

    async def go():
        s = Signal(d, cli)
        assert (await s.link())["uri"].startswith("sgnl://linkdevice")
        await s.linking
        assert (await s.status())["linked"]
        got = (await s.inbox(0))["items"]
        assert got[0]["text"] == "Привет" and got[0]["chat"] == "+4917"
        await s.send({"chat": "+4917", "text": "Ок"})
    asyncio.run(go())
    acc = json.loads((d / "account.json").read_text())
    assert acc["who"] == "*** 5678" and mode(d / "account.json") == 0o600 and mode(d / "inbox.jsonl") == 0o600
    assert json.loads(Path(cli + ".sent").read_text()) == ["send", "-m", "Ок", "+4917"]


def test_whatsapp_qr_and_inbox_with_fake_node(tmp_path):
    from gas_pult.messengers.wa import WhatsApp
    node = fake_exe(tmp_path, "node", """
        import json, sys
        print(json.dumps({"ev": "qr", "qr": "2@ref,key1,key2,adv"}), flush=True)
        print(json.dumps({"ev": "msg", "chat": "49@s.whatsapp.net", "name": "Анна", "from": "Анна", "ts": 5,
                          "text": "Привет"}), flush=True)
        for line in sys.stdin:
            pass
    """)
    mods = tmp_path / "mods"
    mods.mkdir()
    M.consent("whatsapp", 1, True)
    d = M.svc_dir("whatsapp")

    async def go():
        w = WhatsApp(d, node, mods)
        assert (await w.link())["uri"] == "2@ref,key1,key2,adv"
        await asyncio.sleep(0.2)
        assert M.inbox_read(d)[0]["text"] == "Привет"
        await w.stop()
    asyncio.run(go())
    assert mode(d / "auth") == 0o700 and (mods / "wa_bridge.mjs").is_file()


# ---------- «Сегодня»: входящие мессенджеров ----------
def test_brief_today_gets_messenger_rows():
    ts = datetime(2026, 11, 22, 14, 5).timestamp()

    def recent(since):
        return ([{"svc": "telegram", "chat": "1", "name": "Анна", "from": "Анна", "ts": ts, "text": "Буду к семи"}],
                [{"id": "msg:telegram", "label": "Telegram", "state": "ok"}])
    rows, st = brief.messenger_rows(0, recent)
    assert rows[0]["text"] == "14:05 · Анна: Буду к семи"
    assert rows[0]["source"] == {"kind": "msg", "label": "Telegram · Анна"} and st[0]["state"] == "ok"
    assert "messengers" in brief.SOURCES


def test_brief_available_lists_connected_messengers():
    M.consent("whatsapp", 1, True)
    M.write_private(M.svc_dir("whatsapp") / "account.json", json.dumps({"connected": True, "who": "*** 1"}))
    assert M.connected() == ["whatsapp"]
    assert brief.chosen({}, {"messengers": [{"id": "whatsapp"}]})["sources"].count("messengers") == 1


def test_disconnect_wipes_session_and_choice():
    M.consent("whatsapp", 1, True)
    d = M.svc_dir("whatsapp")
    (d / "auth").mkdir()
    (d / "auth" / "creds.json").write_text("{}")
    M.write_private(d / "account.json", json.dumps({"connected": True}))
    M.inbox_append(d, [{"chat": "1", "text": "x", "ts": 1}])
    panel.drop_mcp("whatsapp", claude=lambda *a: None)
    M.disconnect("whatsapp")
    assert not any(x.name in ("auth", "account.json", "inbox.jsonl", "consent.json") for x in d.iterdir())


def test_owner_only_paths():
    from gas_pult import access
    assert set(access.MESSENGERS) <= access.OWNER_ONLY
    assert not set(access.MESSENGERS) & access.SPACE_OK


def test_backend_for_each_service(monkeypatch):
    """Подмодуль signal_cli не должен затирать функцию пакета (22.11: мост Signal падал на старте)."""
    from gas_pult.messengers import signal_cli, wa  # noqa: F401 — как в процессе моста
    monkeypatch.setenv("GAS_MSG_SIGNAL_CLI", "/bin/true")
    monkeypatch.setenv("GAS_MSG_NODE", "/bin/true")
    assert callable(M.signal_bin)
    assert type(H.backend_for("signal", M.svc_dir("signal"))).__name__ == "Signal"
    assert type(H.backend_for("whatsapp", M.svc_dir("whatsapp"))).__name__ == "WhatsApp"
