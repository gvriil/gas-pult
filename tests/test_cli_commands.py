"""Команды ``gas-pult …`` (cli.py): проверка, голоса, служба, речь, панель, вход, почта, мосты, секреты.

План модульного монолита (docs/MONOLITH-PLAN.md): у ``cli.py`` было 58 % покрытия — до переноса покрываем основную
логику. Всё внешнее подменено: systemctl/launchctl, Telegram, сеть, ввод пароля; домашняя папка — временная.
"""

import argparse
import io
import json
import subprocess
import sys
import typing

import pytest

from gas_pult import cli, config, rogroup, setup
from gas_pult.config import Config


@pytest.fixture(autouse=True)
def no_real_processes(monkeypatch):
    """Страховка: настоящий systemctl, launchctl, loginctl или tmux из теста не запустится — подмена обязательна."""
    def refuse(cmd, *a, **k):
        pytest.fail(f"тест запустил настоящий процесс: {cmd}")
    monkeypatch.setattr(cli.subprocess, "run", refuse)
    FakeApi.calls.clear()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("GAS_PULT_TOKEN", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    return tmp_path


def ns(**kw):
    return argparse.Namespace(**kw)


class FakeApi:
    calls: typing.ClassVar[list] = []

    def __init__(self, token):
        self.token = token

    def __call__(self, method, **kw):
        FakeApi.calls.append((method, kw))
        if method == "getMe":
            if self.token == "bad":
                raise cli.TelegramError("getMe", "401 Unauthorized")
            return {"username": "test_bot"}
        return {}

    def redact(self, e):
        return str(e)


def no_config(monkeypatch):
    def boom():
        raise config.ConfigError("нет настроек: gas-pult init")
    monkeypatch.setattr(config, "load", boom)


def test_doctor_reports_and_exit_code(home, monkeypatch, capsys):
    monkeypatch.setattr(config, "load", lambda: Config(token="1:T", owners=[1]))
    monkeypatch.setattr(setup, "status", lambda claude: {"ready": False, "checks": [
        {"name": "tmux", "ok": True, "hint": ""}, {"name": "Claude Code", "ok": False, "hint": "установите"}]})
    monkeypatch.setattr(cli, "Api", FakeApi)
    monkeypatch.setattr(cli.catalog, "installed", lambda personal=False: [])
    monkeypatch.setattr(cli.catalog, "has", lambda name: False)
    monkeypatch.setattr(rogroup, "checks", lambda: [("группа pult-ro", True, "")])
    from gas_pult import asr
    monkeypatch.setattr(asr, "status", lambda: None)
    with pytest.raises(SystemExit) as e:
        cli.cmd_doctor(None)
    out = capsys.readouterr().out
    assert e.value.code == 1 and "✓ бот @test_bot" in out and "✗ Claude Code — установите" in out
    assert "✗ голос: нет" in out and "· распознавание потоком" in out and "мастер входа" in out


def test_doctor_without_config(home, monkeypatch, capsys):
    no_config(monkeypatch)
    with pytest.raises(SystemExit) as e:
        cli.cmd_doctor(None)
    assert e.value.code == 1 and "✗ настройки — нет настроек" in capsys.readouterr().out


def test_voices_list_and_install(home, monkeypatch, capsys):
    monkeypatch.setattr(cli.catalog, "installed", lambda personal=False: ["irina"])
    cli.cmd_voices(ns(action="list", names=[]))
    out = capsys.readouterr().out
    assert "Piper" in out and "Silero" in out and "✓ irina" in out
    got = []
    monkeypatch.setattr(cli.catalog, "install", lambda n: got.append(n))
    nc = next(iter(cli.catalog.NONCOMMERCIAL))
    cli.cmd_voices(ns(action="install", names=[nc]))
    assert got == [nc] and "лицензия только некоммерческая" in capsys.readouterr().out

    def fail(n):
        raise RuntimeError("нет сети")
    monkeypatch.setattr(cli.catalog, "install", fail)
    with pytest.raises(SystemExit, match="нет сети"):
        cli.cmd_voices(ns(action="install", names=["irina"]))


def test_service_install_and_uninstall_linux(home, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "Linger=no\n", "")
    monkeypatch.setattr(cli.subprocess, "run", run)
    monkeypatch.setattr(rogroup, "ready", lambda: (None, None))
    cli.cmd_service(ns(action="install"))
    unit = home / ".config/systemd/user" / cli.UNIT
    text = unit.read_text()
    assert "ExecStart=" in text and "-m gas_pult run" in text and "KillMode=process" in text
    assert ["systemctl", "--user", "enable", "--now", cli.UNIT] in calls
    assert "enable-linger" in capsys.readouterr().out
    cli.cmd_service(ns(action="uninstall"))
    assert not unit.exists() and ["systemctl", "--user", "daemon-reload"] in calls


def test_service_install_macos(home, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = []
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    cli.cmd_service(ns(action="install"))
    plist = home / "Library/LaunchAgents" / f"{cli.AGENT}.plist"
    assert plist.exists() and any(c[:2] == ["launchctl", "bootstrap"] for c in calls)
    cli.cmd_service(ns(action="uninstall"))
    assert not plist.exists() and "служба удалена" in capsys.readouterr().out


def test_asr_status_check_uninstall(home, monkeypatch, capsys):
    from gas_pult import asr
    from gas_pult.asr import install
    monkeypatch.setattr(asr, "status", lambda: None)
    with pytest.raises(SystemExit) as e:
        cli.cmd_asr(ns(action="status", file=None))
    assert e.value.code == 1 and "не запущена" in capsys.readouterr().out
    monkeypatch.setattr(asr, "status", lambda: "T-one, 1 поток")
    with pytest.raises(SystemExit) as e:
        cli.cmd_asr(ns(action="status", file=None))
    assert e.value.code == 0
    with pytest.raises(SystemExit, match="asr check"):
        cli.cmd_asr(ns(action="check", file=None, realtime=False))
    done = []
    monkeypatch.setattr(install, "uninstall", lambda: done.append(1))
    cli.cmd_asr(ns(action="uninstall"))
    assert done == [1]

    def broken(*a):
        raise OSError("нет места")
    monkeypatch.setattr(install, "install", broken)
    with pytest.raises(SystemExit, match="нет места"):
        cli.cmd_asr(ns(action="install", python="python3", model=None, enable=False))


def test_webapp_and_run(home, monkeypatch):
    no_config(monkeypatch)
    with pytest.raises(SystemExit, match="нет настроек"):
        cli.cmd_webapp(ns(tunnel=False, port=8765, url=None))
    with pytest.raises(SystemExit, match="нет настроек"):
        cli.cmd_run(None)
    cfg = Config(token="1:T", owners=[1])
    monkeypatch.setattr(config, "load", lambda: cfg)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="cloudflared"):
        cli.cmd_webapp(ns(tunnel=True, port=8765, url=None))
    from gas_pult import bot, webapp
    served, ran = [], []
    monkeypatch.setattr(webapp, "serve", lambda c, port, tunnel, url: served.append((c, port, tunnel, url)))
    cli.cmd_webapp(ns(tunnel=False, port=9000, url="https://x"))
    assert served == [(cfg, 9000, False, "https://x")]
    monkeypatch.setattr(bot, "Pult", lambda c: type("P", (), {"run": lambda self: ran.append(c)})())
    cli.cmd_run(None)
    assert ran == [cfg]


def test_init_with_token_and_owner(home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Api", FakeApi)
    monkeypatch.setenv("GAS_PULT_TOKEN", "1:T")
    saved = []
    monkeypatch.setattr(config, "save", lambda owners, token: saved.append((owners, token)) or home / "cfg/config.toml")
    cli.cmd_init(ns(owner=[42]))
    assert saved == [([42], "1:T")] and "✓ бот @test_bot" in capsys.readouterr().out
    hello = "✅ gas-pult подключён. Запустите службу: gas-pult service install"
    assert ("sendMessage", {"chat_id": 42, "text": hello}) in FakeApi.calls
    monkeypatch.setenv("GAS_PULT_TOKEN", "bad")
    with pytest.raises(SystemExit, match="Токен не подошёл"):
        cli.cmd_init(ns(owner=[42]))


def test_geoip_status(home, monkeypatch, capsys):
    cli.cmd_geoip(ns(action="status", ips=[]))
    assert "Базы GeoIP нет" in capsys.readouterr().out
    from gas_pult import country

    class G:
        def __init__(self, folder):
            self.p = home / "geo.mmdb"
            self.p.write_bytes(b"x")

        def path(self):
            return self.p

        def lookup(self, ip):
            return "NL" if ip == "1.2.3.4" else None
    monkeypatch.setattr(country, "GeoIP", G)
    cli.cmd_geoip(ns(action="status", ips=["1.2.3.4", "5.6.7.8"]))
    out = capsys.readouterr().out
    assert "1.2.3.4 → NL" in out and "5.6.7.8 → нет данных" in out

    def fail(folder):
        raise RuntimeError("нет сети")
    monkeypatch.setattr(country, "update", fail)
    with pytest.raises(SystemExit, match="GeoIP: нет сети"):
        cli.cmd_geoip(ns(action="update", ips=[]))


def test_email_status_password_test(home, monkeypatch, capsys):
    from gas_pult import emailcode, providers
    keys = {}
    monkeypatch.setattr(providers, "save_key", lambda k, v: keys.__setitem__(k, v))
    monkeypatch.setattr(providers, "load_keys", lambda: keys)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": " app-pass ")
    cli.cmd_email(ns(action="password", to=""))
    assert keys[emailcode.PASSWORD_KEY] == "app-pass" and "Сохранён" in capsys.readouterr().out
    monkeypatch.setattr(config, "load", lambda: Config(token="1:T", owners=[1]))
    monkeypatch.setattr(emailcode, "smtp_settings", lambda section: None)
    cli.cmd_email(ns(action="status", to=""))
    assert "Почта выключена" in capsys.readouterr().out
    smtp = type("S", (), {"host": "smtp.example.com", "port": 465, "user": "u", "sender": "u@example.com"})()
    monkeypatch.setattr(emailcode, "smtp_settings", lambda section: smtp)
    sent = []
    monkeypatch.setattr(emailcode, "message", lambda s, to, subj, body: (to, subj))
    monkeypatch.setattr(emailcode, "send", lambda s, m: sent.append(m))
    cli.cmd_email(ns(action="test", to="Name@Example.com"))
    assert sent and sent[0][0] == "name@example.com" and "Письмо отправлено" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="Укажите адрес"):
        cli.cmd_email(ns(action="test", to="не адрес"))


def test_oidc_secret_and_status(home, monkeypatch, capsys):
    from gas_pult import providers
    with pytest.raises(SystemExit, match=r"google \| yandex"):
        cli.cmd_oidc(ns(action="secret", provider="vk", url=""))
    keys = {}
    monkeypatch.setattr(providers, "save_key", lambda k, v: keys.__setitem__(k, v))
    monkeypatch.setattr(providers, "load_keys", lambda: keys)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "")
    cli.cmd_oidc(ns(action="secret", provider="google", url=""))
    assert "Удалён" in capsys.readouterr().out
    monkeypatch.setattr(config, "load", lambda: Config(token="1:T", owners=[1]))
    cli.cmd_oidc(ns(action="status", provider="", url=""))
    out = capsys.readouterr().out
    assert "выключен" in out and "client_id" in out


def test_tgbiz_without_token_and_bridge_confirm(home, monkeypatch):
    from gas_pult.connectors import tgbiz_mcp

    def no_key():
        raise RuntimeError("файла нет")
    monkeypatch.setattr(tgbiz_mcp, "_key", no_key)
    with pytest.raises(SystemExit, match="нет токена бота: файла нет"):
        cli.cmd_tgbiz(ns())

    with pytest.raises(SystemExit, match="только кнопкой «Да» в панели"):   # штаб 22.11: «Да» — только в панели
        cli.cmd_bridge_confirm(ns(id="abc"))


def test_bridge_code_and_mcp(home, monkeypatch, capsys):
    from gas_pult import webapp
    monkeypatch.setattr(webapp, "bridge_local_token", lambda data: "local-token")
    seen = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=0):
        seen.append((req.full_url, req.headers.get("X-gp-local"), req.data))
        if req.full_url.endswith("/api/bridge/code"):
            return Resp(json.dumps({"code": "ABC-123"}).encode())
        return Resp(json.dumps({"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}).encode())
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    cli.cmd_bridge_code(ns(panel="http://127.0.0.1:8765/", url="https://pult.example"))
    assert "Код: ABC-123" in capsys.readouterr().out and seen[0][1] == "local-token"
    monkeypatch.setattr(sys, "stdin", io.StringIO('\n{"jsonrpc":"2.0","id":7,"method":"tools/list"}\nне json\n'))
    cli.cmd_bridge_mcp(ns(panel="http://127.0.0.1:8765", device=""))
    out = capsys.readouterr().out.strip().splitlines()
    assert json.loads(out[0])["result"] == {"ok": True} and len(seen) == 2


def test_secrets_status_install(home, monkeypatch, capsys):
    from gas_pult import injection_guard, secrets_guard
    monkeypatch.setattr(secrets_guard, "installed", lambda d: True)
    monkeypatch.setattr(injection_guard, "installed", lambda d: False)
    with pytest.raises(SystemExit) as e:
        cli.cmd_secrets(ns(action="status", config_dir=str(home / ".claude"), python=None))
    assert e.value.code == 1 and "не стоит" in capsys.readouterr().out
    did = []
    monkeypatch.setattr(secrets_guard, "install", lambda d, python=None, remove=False: did.append(("s", remove)))
    monkeypatch.setattr(injection_guard, "install", lambda d, python=None, remove=False: did.append(("i", remove)))
    cli.cmd_secrets(ns(action="install", config_dir=str(home / ".claude"), python=None))
    assert did == [("s", False), ("i", False)] and "со скрытием" in capsys.readouterr().out

    def bad(d, python=None, remove=False):
        raise ValueError("папки нет")
    monkeypatch.setattr(secrets_guard, "install", bad)
    with pytest.raises(SystemExit, match="папки нет"):
        cli.cmd_secrets(ns(action="uninstall", config_dir=str(home / ".claude"), python=None))


def test_last_and_own_window(home, monkeypatch, capsys):
    monkeypatch.setattr(cli.transcripts, "last_answer", lambda path: "")
    cli.cmd_last(ns(path="."))
    assert "ответов не найдено" in capsys.readouterr().out
    assert cli.own_window() == ("", "")
    monkeypatch.setenv("TMUX_PANE", "%3")
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "@5\tgas-pult\n", ""))
    assert cli.own_window() == ("@5", "gas-pult")


def test_main_parses_every_command_help(home, capsys):
    """Каждая подкоманда разбирается (--help — без побочных действий)."""
    for cmd in ("run", "init", "doctor", "voices", "service", "asr", "webapp", "geoip", "offer", "invite", "email",
                "oidc", "secrets", "usage", "notify", "task", "tgbiz", "bridge-code", "bridge-confirm", "bridge-mcp",
                "pi", "inbox", "last"):
        with pytest.raises(SystemExit) as e:
            cli.main([cmd, "--help"])
        out = capsys.readouterr().out
        assert e.value.code == 0 and "usage:" in out and cmd in out, cmd
