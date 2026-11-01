"""Командная строка: ``gas-pult [run|init|doctor|voices|service|webapp|geoip|last|version]``."""

from __future__ import annotations

import argparse
import getpass
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

from gas_pult import __version__, config, setup, transcripts
from gas_pult.telegram import Api, TelegramError
from gas_pult.voice import catalog

UNIT = "gas-pult.service"
AGENT = "com.github.gvriil.gas-pult"


def cmd_run(_):
    from gas_pult.bot import Pult

    try:
        cfg = config.load()
    except config.ConfigError as e:
        raise SystemExit(str(e)) from None
    Pult(cfg).run()


def cmd_init(a):
    """Мастер: токен (скрытым вводом) → проверка → ID владельца по первому сообщению боту → config.toml."""
    print("gas-pult: настройка.\n1) В Telegram откройте @BotFather → /newbot → скопируйте токен.")
    token = os.environ.get("GAS_PULT_TOKEN") or getpass.getpass("Токен бота (ввод скрыт): ").strip()
    api = Api(token)
    try:
        me = api("getMe")
    except (TelegramError, OSError) as e:
        raise SystemExit(f"Токен не подошёл: {api.redact(e)}") from None
    print(f"   ✓ бот @{me['username']}")
    owners = a.owner
    if not owners:
        print(f"2) Напишите своему боту @{me['username']} любое сообщение (например /start) — жду 3 минуты…")
        owners = [_wait_owner(api)]
    path = config.save(owners, token)
    print(f"   ✓ владелец {owners} · настройки: {path} · токен: {path.parent / 'token'} (0600)")
    try:
        api("sendMessage", chat_id=owners[0], text="✅ gas-pult подключён. Запустите службу: gas-pult service install")
    except TelegramError:
        pass
    print("\nДальше:\n  gas-pult voices install irina   # голос (нужен пакет gas-pult[voice])\n"
          "  gas-pult doctor                 # проверка\n  gas-pult service install        # запуск в фоне")


def _wait_owner(api: Api) -> int:
    offset, deadline = None, time.time() + 180
    for u in api("getUpdates", timeout=0):   # старые сообщения не считаем
        offset = u["update_id"] + 1
    while time.time() < deadline:
        for u in api("getUpdates", timeout=30, **({"offset": offset} if offset else {})):
            offset = u["update_id"] + 1
            frm = (u.get("message") or {}).get("from") or {}
            if frm.get("id") and not frm.get("is_bot"):
                name = frm.get("username") or frm.get("first_name") or ""
                answer = input(f"   Сообщение от {name} (ID {frm['id']}). Это вы? [Y/n] ").strip().lower()
                if answer in ("", "y", "yes", "д", "да"):
                    api("getUpdates", offset=offset, timeout=0)    # подтверждаем, чтобы бот не увидел его снова
                    return frm["id"]
    raise SystemExit("Сообщение не пришло. Запустите `gas-pult init --owner <ваш ID>` (ID подскажет @userinfobot).")


def cmd_doctor(_):
    ok = True

    def check(name, good, hint=""):
        nonlocal ok
        ok &= bool(good)
        print(f"{'✓' if good else '✗'} {name}" + ("" if good or not hint else f" — {hint}"))

    check(f"Python {sys.version.split()[0]}", sys.version_info >= (3, 11), "нужен 3.11+")
    check("tmux", shutil.which("tmux"), "sudo apt install tmux / brew install tmux")
    try:
        cfg = config.load()
    except config.ConfigError as e:
        check("настройки", False, str(e))
        return sys.exit(1)
    check(f"настройки: владельцы {cfg.owners}, сессия «{cfg.session}», хост «{cfg.host}»", True)
    st = setup.status(cfg.claude)                      # то же, что «Проверка» в боте и панели
    for c in st["checks"]:
        if c["name"] != "tmux":
            check(c["name"], c["ok"], c["hint"])
    if not st["ready"]:
        print(f"  Бот и панель работают и без Claude: /start в боте — мастер входа. Вручную — {setup.DOC_URL}")
    try:
        check(f"бот @{Api(cfg.token)('getMe')['username']}", True)
    except (TelegramError, OSError) as e:
        check("бот", False, Api(cfg.token).redact(e))
    voices = catalog.installed()
    check("голос: " + (", ".join(catalog.label(v) for v in voices) or "нет"), voices,
          'pip install "gas-pult[voice]" && gas-pult voices install irina (необязательно)')
    check("распознавание голосовых (faster-whisper)", catalog.has("faster_whisper"), 'pip install "gas-pult[voice]"')
    check("ffmpeg", catalog.has("imageio_ffmpeg") or shutil.which("ffmpeg"), "pip install imageio-ffmpeg")
    sys.exit(0 if ok else 1)


def cmd_voices(a):
    if a.action == "list" or not a.names:
        have = set(catalog.installed())
        for group, names in (("Piper (быстрые, gas-pult[voice])", catalog.PIPER),
                             ("Silero v5 (естественнее, gas-pult[silero])", catalog.SILERO)):
            print(group)
            for n, lbl in names.items():
                print(f"  {'✓' if n in have else ' '} {n:8} {lbl}")
        return
    for n in a.names:
        try:
            catalog.install(n)
            print(f"✓ {n}")
        except (RuntimeError, OSError) as e:
            raise SystemExit(f"✗ {n}: {e}") from None


def _python_cmd() -> list[str]:
    return [sys.executable, "-m", "gas_pult", "run"]


def cmd_service(a):
    path_env = os.pathsep.join(dict.fromkeys([str(Path(sys.executable).parent), str(Path.home() / ".local/bin"),
                                              "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]))
    if sys.platform == "darwin":
        plist = Path.home() / "Library/LaunchAgents" / f"{AGENT}.plist"
        target = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", f"{target}/{AGENT}"], capture_output=True)
        if a.action == "uninstall":
            plist.unlink(missing_ok=True)
            return print("✓ служба удалена")
        log = config.data_dir() / "gas-pult.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(plistlib.dumps({"Label": AGENT, "ProgramArguments": _python_cmd(), "RunAtLoad": True,
                                          "KeepAlive": True, "EnvironmentVariables": {"PATH": path_env},
                                          "StandardOutPath": str(log), "StandardErrorPath": str(log)}))
        subprocess.run(["launchctl", "bootstrap", target, str(plist)], check=True)
        return print(f"✓ служба запущена (launchd). Лог: {log}")
    unit = Path.home() / ".config/systemd/user" / UNIT
    if a.action == "uninstall":
        subprocess.run(["systemctl", "--user", "disable", "--now", UNIT], capture_output=True)
        unit.unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"])
        return print("✓ служба удалена")
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(f"""[Unit]
Description=gas-pult — Telegram-пульт сессий Claude Code
After=network-online.target
Wants=network-online.target

[Service]
ExecStart={" ".join(_python_cmd())}
Environment=PATH={path_env}
Restart=always
RestartSec=10
# tmux, запущенный пультом, живёт в своей группе — не убивать его (и Claude в нём) при перезапуске
KillMode=process

[Install]
WantedBy=default.target
""")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", UNIT], check=True)
    subprocess.run(["systemctl", "--user", "restart", UNIT], check=True)
    print(f"✓ служба запущена: systemctl --user status {UNIT} · лог: journalctl --user -u {UNIT} -f")
    linger = subprocess.run(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "Linger"],
                            capture_output=True, text=True).stdout
    if "Linger=yes" not in linger:
        print(f"  Чтобы пульт работал без входа в систему: sudo loginctl enable-linger {os.environ.get('USER', '')}")


def cmd_webapp(a):
    from gas_pult import webapp

    try:
        cfg = config.load()
    except config.ConfigError as e:
        raise SystemExit(str(e)) from None
    if a.tunnel and not shutil.which("cloudflared"):
        raise SystemExit("Для --tunnel нужен cloudflared: https://developers.cloudflare.com/cloudflare-one/"
                         "connections/connect-networks/downloads/")
    webapp.serve(cfg, a.port, a.tunnel, a.url)


def cmd_geoip(a):
    """База GeoIP (db-ip lite, CC BY 4.0): ``status`` — есть ли и от какого числа; ``update`` — скачать свежую.
    Скачивается только по этой команде владельца; страна по IP дальше ищется локально, без внешних запросов."""
    from gas_pult import country

    folder = config.data_dir() / "geoip"
    if a.action == "update":
        print(f"Скачиваю базу стран по IP с db-ip.com в {folder} …", flush=True)
        try:
            path = country.update(folder)
        except RuntimeError as e:
            raise SystemExit(f"GeoIP: {e}") from None
        print(f"✓ {path} ({path.stat().st_size // 1024} КБ). {country.ATTRIBUTION} — {country.ATTRIBUTION_URL}, "
              "лицензия CC BY 4.0.\n  Панель подхватит новый файл сама, перезапуск не нужен.")
        return
    g = country.GeoIP(folder)
    if not (p := g.path()):
        return print(f"Базы GeoIP нет ({folder}). Страна по IP — «нет данных». Загрузить: gas-pult geoip update")
    print(f"База GeoIP: {p} · от {time.strftime('%d.%m.%Y', time.localtime(p.stat().st_mtime))} · "
          f"{country.ATTRIBUTION} ({country.ATTRIBUTION_URL}, CC BY 4.0)")
    for ip in a.ips:
        print(f"  {ip} → {g.lookup(ip) or 'нет данных'}")


def cmd_last(a):
    print(transcripts.last_answer(os.path.abspath(a.path)) or "ответов не найдено")


def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(prog="gas-pult", description="Telegram-пульт для сессий Claude Code в tmux.")
    p.add_argument("-V", "--version", action="version", version=f"gas-pult {__version__}")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="запустить пульт (по умолчанию)").set_defaults(fn=cmd_run)
    s = sub.add_parser("init", help="настройка: токен бота и владелец")
    s.add_argument("--owner", type=int, action="append", help="Telegram ID владельца (можно несколько)")
    s.set_defaults(fn=cmd_init)
    sub.add_parser("doctor", help="проверить установку").set_defaults(fn=cmd_doctor)
    s = sub.add_parser("voices", help="голоса: list | install <имя…>")
    s.add_argument("action", choices=["list", "install"], nargs="?", default="list")
    s.add_argument("names", nargs="*")
    s.set_defaults(fn=cmd_voices)
    s = sub.add_parser("service", help="фоновая служба: install | uninstall")
    s.add_argument("action", choices=["install", "uninstall"])
    s.set_defaults(fn=cmd_service)
    s = sub.add_parser("webapp", help="Mini App: панель сессий в Telegram")
    s.add_argument("--port", type=int, default=8765)
    g = s.add_mutually_exclusive_group()
    g.add_argument("--tunnel", action="store_true", help="временный HTTPS-адрес Cloudflare (нужен cloudflared)")
    g.add_argument("--url", help="постоянный HTTPS-адрес перед сервером (обратный прокси)")
    s.set_defaults(fn=cmd_webapp)
    s = sub.add_parser("geoip", help="страна по IP: status [IP…] | update (скачать базу db-ip lite)")
    s.add_argument("action", choices=["status", "update"], nargs="?", default="status")
    s.add_argument("ips", nargs="*", help="проверить адреса (только для status)")
    s.set_defaults(fn=cmd_geoip)
    s = sub.add_parser("last", help="последний ответ Claude в папке (текстом)")
    s.add_argument("path", nargs="?", default=".")
    s.set_defaults(fn=cmd_last)
    a = p.parse_args(argv)
    (getattr(a, "fn", None) or cmd_run)(a)
