"""Командная строка: ``gas-pult [run|init|doctor|voices|service|webapp|geoip|offer|email|last|version]``."""

from __future__ import annotations

import argparse
import getpass
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from gas_pult import __version__, config, rogroup, setup, transcripts
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
    for name, good, hint in rogroup.checks():          # демо-пространства: у бота и панели должна быть pult-ro
        check(name, good, hint)
    sys.exit(0 if ok else 1)


def cmd_voices(a):
    if a.action == "list" or not a.names:
        have = set(catalog.installed(personal=True))
        for group, names in (("Piper (gas-pult[voice]) — запасной синтез: в выборе не показывается, читает, когда "
                              "других голосов нет", catalog.PIPER),
                             ("Silero v5 (естественнее, gas-pult[silero]) — демо, CC BY-NC-SA: только некоммерческое "
                              "использование, видит лишь владелец при personal_voices = true", catalog.SILERO)):
            print(group)
            for n, lbl in names.items():
                print(f"  {'✓' if n in have else ' '} {n:8} {lbl}")
        return
    for n in a.names:
        if n in catalog.NONCOMMERCIAL:
            print(f"! {n}: Silero — лицензия только некоммерческая (CC BY-NC-SA). В пульте голос появится у владельца "
                  "лишь при personal_voices = true в config.toml; для клиентов не включайте.")
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
    _group, wrap = rogroup.ready()                     # группа pult-ro есть — бот запускается с ней (sg / newgrp)
    unit.write_text(f"""[Unit]
Description=gas-pult — Telegram-пульт сессий Claude Code
After=network-online.target
Wants=network-online.target

[Service]
ExecStart={rogroup.exec_start(_python_cmd(), wrap)}
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
    if wrap:
        print(f"  бот запускается с группой {rogroup.GROUP_RO} через {wrap[0]}; панель (gas-pult webapp) получает её "
              "сама при запуске")
    elif _group is not None and rogroup.member(_group):
        print(f"  ! группа {rogroup.GROUP_RO} у пульта не появится: {rogroup.HINT_TOOL}")
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


def invite_qr(link: str, hint: str) -> Path:
    """PNG с QR ссылки — в данных пульта (папка 0700, файл 0600): показать с экрана или распечатать."""
    from gas_pult import qr
    from gas_pult.config import data_dir

    d = data_dir() / "invites"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    d.chmod(0o700)
    f = d / f"qr-{hint}.png"
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(qr.png_of(link))
    f.chmod(0o600)
    return f


def cmd_invite(a):
    """Одноразовые приглашения тестировщиков (invites.py, docs/TENANTS.md): ссылка на 24 часа, пространство и роль;
    вход по ней (или по короткому коду, или по QR) — без Telegram, именем, или через Telegram. list — какие есть;
    revoke — отозвать."""
    from gas_pult import invites

    try:
        if a.action == "create":
            if not a.arg:
                raise SystemExit("Укажите пространство: gas-pult invite create <имя>")
            inv = invites.new(a.arg, a.role)
            base = (a.url or "").rstrip("/")
            link = f"{base}/invite/{inv['code']}"
            print(f"✓ Приглашение в «{a.arg}» ({a.role}), 24 часа, один вход — ссылкой, QR или кодом.")
            print(f"  Ссылка: {link}" if base else
                  f"  Путь: /invite/{inv['code']} — перед ним адрес панели (--url https://…)")
            print(f"  Код:    {inv['short']}  (экран входа → «Есть код приглашения?»)")
            print(f"  QR:     {invite_qr(link, inv['hint'])}" if base else
                  "  QR:     нужен адрес панели — добавьте --url https://…")
            print(f"  Отозвать: gas-pult invite revoke {inv['hint']}")
        elif a.action == "list":
            items = invites.listing()
            if not items:
                return print("Приглашений нет.")
            for x in items:
                till = time.strftime("%d.%m %H:%M", time.localtime(x["exp"]))
                print(f"{x['hint']}…  {x['tenant']} · {x['role']} · {x['state']} · до {till}")
        elif a.action == "revoke":
            if not a.arg:
                raise SystemExit("Укажите код: gas-pult invite revoke <код>")
            print(f"✓ Отозвано: {invites.revoke(a.arg)}… — ссылка больше не работает.")
    except (ValueError, OSError) as e:
        raise SystemExit(f"Приглашение: {e}") from None


def cmd_offer(a):
    """Предложения GASTECH (offers.py, docs/OFFERS.md): new — новый неугадываемый код и файл 0600 в
    ``<config>/offers/``; list — какие есть; revoke — отозвать (страница сразу отвечает 404)."""
    from gas_pult import offers

    try:
        if a.action == "new":
            if a.file:
                text = Path(a.file).read_text(encoding="utf-8")
            elif a.name:
                text = offers.example_text()
            else:
                raise SystemExit("Укажите файл-шаблон или --name \"Имя бизнеса\" (тогда — пример с этим именем).\n"
                                 "Пример: gas-pult offer example > my.toml")
            if a.expires and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.expires):
                raise SystemExit("--expires — дата ГГГГ-ММ-ДД")
            code, path = offers.create(text, a.name or "", a.expires or "")
            base = (a.url or "").rstrip("/")
            print(f"✓ Предложение: {path} (0600)")
            print(f"  Ссылка: {base}/offer/{code}" if base else
                  f"  Путь: /offer/{code} — перед ним адрес панели (--url https://…)")
            print("  Отозвать: gas-pult offer revoke " + code)
        elif a.action == "list":
            items = offers.listing()
            if not items:
                return print(f"Предложений нет ({offers.offers_dir()}).")
            for x in items:
                till = f" · до {x['expires']}" if x["expires"] else ""
                print(f"{x['code']}  {x['business']} · {x['state']}{till} · {', '.join(x['modules'])}")
        elif a.action == "revoke":
            if not a.file:
                raise SystemExit("Укажите код: gas-pult offer revoke <код>")
            print(f"✓ Отозвано: {offers.revoke(a.file)} — страница отвечает «не найдена».")
        elif a.action == "example":
            print(offers.example_text(), end="")
    except offers.OfferError as e:
        raise SystemExit(f"Предложение: {e}") from None
    except OSError as e:
        raise SystemExit(f"Предложение: {e}") from None


def cmd_email(a):
    """Почта для входа по коду (emailcode.py, docs/AUTH.md): status — включена ли; password — пароль приложения SMTP
    в secrets.json (0600, ввод скрыт); test <адрес> — пробное письмо, чтобы проверить настройки до кнопки в панели."""
    from gas_pult import emailcode, providers

    if a.action == "password":
        pw = getpass.getpass("Пароль приложения SMTP (ввод скрыт; пусто — удалить): ").strip()
        providers.save_key(emailcode.PASSWORD_KEY, pw or None)
        return print(f"✓ {'Сохранён' if pw else 'Удалён'}: {providers.secrets_file()} (0600). "
                     "Перезапустите панель: systemctl --user restart gas-pult-webapp")
    try:
        section = config.load().email
    except config.ConfigError as e:
        raise SystemExit(str(e)) from None
    smtp = emailcode.smtp_settings(section)
    if not smtp:
        miss = [k for k in ("host", "user") if not (section.get(k) or (k == "host" and section.get("provider")))]
        if not (section.get("password") or providers.load_keys().get(emailcode.PASSWORD_KEY)):
            miss.append("пароль (gas-pult email password)")
        return print("Почта выключена: в config.toml нет секции [email] или в ней не хватает: "
                     f"{', '.join(miss) or '—'}. Пример — config.example.toml, подробно — docs/AUTH.md.")
    print(f"Почта включена: {smtp.host}:{smtp.port} (SSL), вход {smtp.user}, отправитель {smtp.sender}.")
    if a.action == "test":
        to = emailcode.normalize(a.to)
        if not to:
            raise SystemExit("Укажите адрес: gas-pult email test name@example.com")
        try:
            emailcode.send(smtp, emailcode.message(smtp, to, "Проверка почты gas-pult",
                                                   "Это пробное письмо: почта пульта настроена верно.\n"))
        except (OSError, emailcode.smtplib.SMTPException) as e:
            raise SystemExit(f"Не отправилось: {type(e).__name__}: {e}") from None
        print(f"✓ Письмо отправлено на {to}.")


def cmd_oidc(a):
    """Вход через Google и Яндекс ID (oidc.py, docs/AUTH.md): status — включён ли; secret google|yandex — секрет
    приложения в secrets.json (0600, ввод скрыт), чтобы не держать его в config.toml."""
    from gas_pult import oidc, providers

    if a.action == "secret":
        if a.provider not in oidc.PROVIDERS:
            raise SystemExit("Укажите, чей секрет: gas-pult oidc secret google | yandex")
        title = oidc.PROVIDERS[a.provider]["title"]
        sec = getpass.getpass(f"Секрет приложения {title} (ввод скрыт; пусто — удалить): ").strip()
        providers.save_key(oidc.secret_key(a.provider), sec or None)
        return print(f"✓ {'Сохранён' if sec else 'Удалён'}: {providers.secrets_file()} (0600). "
                     "Перезапустите панель: systemctl --user restart gas-pult-webapp")
    try:
        cfg = config.load()
    except config.ConfigError as e:
        raise SystemExit(str(e)) from None
    o = oidc.Oidc({"google": cfg.google, "yandex": cfg.yandex}, None, cfg.data / "oidc.json", base=lambda: a.url or "")
    for p, meta in oidc.PROVIDERS.items():
        sec, s = getattr(cfg, p), o.settings(p)
        if s:
            print(f"{meta['title']}: включён · client_id …{s['client_id'][-6:]} · возврат {s['redirect_uri']}")
            continue
        miss = [x for x, ok in (("client_id", sec.get("client_id")),
                                (f"секрет (gas-pult oidc secret {p})",
                                 sec.get("client_secret") or providers.load_keys().get(oidc.secret_key(p))),
                                ("redirect_uri (или --url панели)", sec.get("redirect_uri") or a.url)) if not ok]
        print(f"{meta['title']}: выключен — в [{p}] config.toml не хватает: {', '.join(miss) or 'https-адреса'}.")


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
    s = sub.add_parser("offer", help="предложения бизнесу: new <файл> | new --name … | list | revoke <код> | example")
    s.add_argument("action", choices=["new", "list", "revoke", "example"])
    s.add_argument("file", nargs="?", help="new — файл-шаблон предложения; revoke — код")
    s.add_argument("--name", help="имя бизнеса (new без файла — пример с этим именем)")
    s.add_argument("--expires", help="последний день работы ссылки, ГГГГ-ММ-ДД")
    s.add_argument("--url", help="адрес панели снаружи — чтобы напечатать готовую ссылку")
    s.set_defaults(fn=cmd_offer)
    s = sub.add_parser("invite", help="приглашение тестировщика: create <пространство> | list | revoke <код>")
    s.add_argument("action", choices=["create", "list", "revoke"])
    s.add_argument("arg", nargs="?", help="create — имя пространства; revoke — код или его первые знаки")
    s.add_argument("--role", choices=["member", "viewer"], default="member", help="роль (по умолчанию участник)")
    s.add_argument("--url", help="адрес панели снаружи — чтобы напечатать готовую ссылку")
    s.set_defaults(fn=cmd_invite)
    s = sub.add_parser("email", help="почта для входа по коду: status | password | test <адрес>")
    s.add_argument("action", choices=["status", "password", "test"], nargs="?", default="status")
    s.add_argument("to", nargs="?", help="test — куда отправить пробное письмо")
    s.set_defaults(fn=cmd_email)
    s = sub.add_parser("oidc", help="вход через Google и Яндекс ID: status [--url …] | secret google|yandex")
    s.add_argument("action", choices=["status", "secret"], nargs="?", default="status")
    s.add_argument("provider", nargs="?", help="secret — google или yandex")
    s.add_argument("--url", help="адрес панели снаружи (как у gas-pult webapp --url) — для адреса возврата")
    s.set_defaults(fn=cmd_oidc)
    s = sub.add_parser("last", help="последний ответ Claude в папке (текстом)")
    s.add_argument("path", nargs="?", default=".")
    s.set_defaults(fn=cmd_last)
    a = p.parse_args(argv)
    fn = getattr(a, "fn", None) or cmd_run
    if fn in (cmd_run, cmd_webapp):
        rogroup.regain()                               # группа pult-ro не дошла от systemd --user — получить её
    fn(a)
