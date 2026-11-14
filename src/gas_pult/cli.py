"""Командная строка: ``gas-pult [run|init|doctor|voices|service|asr|webapp|geoip|offer|email|secrets|last|version]``."""

from __future__ import annotations

import argparse
import getpass
import os
import plistlib
import re
import shutil
import subprocess
import sys
import threading
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
    from gas_pult import asr  # необязательная служба — на итог проверки не влияет
    print(f"{'✓' if asr.status() else '·'} распознавание потоком (служба T-one)" +
          ("" if asr.status() else " — не запущена, голос распознаёт whisper; gas-pult asr install --enable"))
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


def cmd_asr(a):
    """Служба распознавания речи T-one (задача 46): install | uninstall | status | check <файл>."""
    from gas_pult import asr
    from gas_pult.asr import install

    if a.action == "install":
        try:
            return install.install(a.python, Path(a.model).expanduser() if a.model else None, a.enable)
        except (OSError, ValueError, subprocess.CalledProcessError) as e:
            raise SystemExit(f"Ошибка: {e}") from None
    if a.action == "uninstall":
        return install.uninstall()
    st = asr.status()
    if a.action == "status":
        print(f"Служба распознавания: {st}" if st else
              "Служба распознавания не запущена — пульт распознаёт whisper. Включить: gas-pult asr install --enable")
        raise SystemExit(0 if st else 1)
    if not a.file:
        raise SystemExit("gas-pult asr check <файл со звуком> [--realtime]")
    if not st:
        raise SystemExit("служба распознавания не запущена")
    try:
        pcm = asr.decode(Path(a.file).expanduser(), 16000)
    except asr.Unavailable as e:
        raise SystemExit(f"Ошибка: {e}") from None
    dur, step = len(pcm) / 32000, 3200                       # кусок 100 мс — как шлёт панель
    with asr.Stream(16000, partials=True) as s:
        t0, first, sent = time.perf_counter(), None, 0.0

        def pump():
            nonlocal sent
            for i in range(0, len(pcm), step):
                if a.realtime:                                # как живой микрофон: кусок — когда он «записан»
                    time.sleep(max(0.0, t0 + (i + step) / 32000 - time.perf_counter()))
                s.audio(pcm[i:i + step])
            sent = time.perf_counter()
            s.end()

        threading.Thread(target=pump, daemon=True).start()
        for ev in s.events(dur + 60):
            if "partial" in ev and first is None and ev["partial"]:
                first = time.perf_counter() - t0
            if "final" in ev:
                lag = time.perf_counter() - sent
                print(f"длина {dur:.1f} с · первый текст {first if first is None else round(first, 2)} с от начала · "
                      f"итог через {lag:.2f} с после конца записи (в службе {ev.get('lag_ms')} мс)")
                return print(ev["final"])
            if "error" in ev:
                raise SystemExit(f"Ошибка: {ev['error']}")


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


def cmd_usage(a):
    """Отчёт по функциям панели сейчас: файл ``usage-ГГГГ-ММ.md`` в данных пульта и текст в консоль. В Telegram
    его шлёт бот сам, 1-го числа."""
    from gas_pult import features

    data = config.data_dir()
    r = features.report(features.Uses(data / "features.json"))
    path = features.write(data, r)
    print(features.markdown(r))
    print(f"Сохранено: {path}")


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


def own_window() -> tuple[str, str]:
    """Окно tmux, из которого запущена команда (агент в сессии пульта): (id, имя); вне tmux — («», «»)."""
    pane = os.environ.get("TMUX_PANE", "")
    if not pane:
        return "", ""
    r = subprocess.run(["tmux", "display-message", "-p", "-t", pane, "#{window_id}\t#{window_name}"],
                       capture_output=True, text=True)
    wid, _, name = r.stdout.strip().partition("\t")
    return (wid, name) if r.returncode == 0 and wid.startswith("@") else ("", "")


def cmd_task(a):
    """Задачи владельца (#203): агент или человек кладёт задачу — она видна сверху в панели и в боте (/tasks)."""
    from gas_pult import tasks

    t = tasks.Tasks(config.data_dir() / "tasks.json")
    if a.action == "list":
        names = {w["id"]: f"{w['idx']}:{w['name']}" for w in _windows()}
        group = None
        for x in t.list():
            if x["status"] == "done" and not a.all:
                continue
            g = "Выполнено" if x["status"] == "done" else f"Q{x['q']} · {tasks.QUADRANTS[x['q']]}" if x["q"] \
                else tasks.QUADRANTS[0]
            if g != group:
                print(("\n" if group else "") + f"== {g}")
                group = g
            print(f"{x['id']}  [{tasks.STATUS_TITLES[x['status']]}] {tasks.TITLES[x['kind']]}: {x['title']}"
                  + (f" · срок {x['due']}" + (" (просрочено)" if x["overdue"] else "") if x.get("due") else "")
                  + (f" — дальше: {x['next']}" if x.get("next") and x["status"] != "done" else "")
                  + (f" · чат {names.get(x['chat'], x['chat'] + ' (окна нет)')}" if x.get("chat") else ""))
        return
    if a.action in ("done", "undo"):
        if not a.id:
            raise SystemExit("нужен id задачи: gas-pult task done <id>")
        try:
            x = t.update(a.id, {"status": "done" if a.action == "done" else "todo"})
        except (ValueError, LookupError) as e:
            raise SystemExit(f"не записал: {e}") from None
        print(f"{x['id']}: {tasks.STATUS_TITLES[x['status']]}")
        return
    d = {k: v for k, v in {"title": a.title, "kind": a.type, "next": a.next, "status": a.status, "link": a.link,
                           "cmd": a.cmd, "phone": a.phone, "to": a.to, "draft": a.draft, "with": a.with_,
                           "when": a.when, "question": a.question,
                           "options": a.option or None, "due": a.due}.items() if v}
    for k in ("urgent", "important"):                  # да/нет — и «нет» тоже значение (не пропускаем)
        if getattr(a, k) != "":
            d[k] = getattr(a, k)
    try:
        if a.q:
            d = tasks.set_quadrant(d, a.q)
        if a.action == "update":
            if not a.id:
                raise SystemExit("нужен id задачи: gas-pult task update <id> --next …")
            if a.chat:                                 # сменить чат задачи (или «none» — отвязать)
                d.update({"chat": "", "sid": ""} if a.chat == "none" else _chat(a.chat))
            if not d:
                raise SystemExit("нечего менять: укажите --next, --status, --chat или поля типа")
            x = t.update(a.id, d)
        else:
            _, name = own_window()
            if a.chat and a.chat != "none":
                d.update(_chat(a.chat))
            elif not a.chat and (own := own_window()[0]):
                d.update({"chat": own, "sid": _sid_of(own)})
            x = t.add(d, by=a.by or (f"агент · {name}" if name else "агент"))
    except (ValueError, LookupError) as e:
        raise SystemExit(f"не записал: {e}") from None
    print(f"задача {x['id']}: {x['title']} [{tasks.STATUS_TITLES[x['status']]}]"
          + (f" · чат {x['chat']}" if x.get("chat") else ""))


def _sid_of(wid: str) -> str:
    """id разговора окна (метка или живой процесс) — по нему задача найдёт чат и после перезапуска окна."""
    return (_window(wid) or {}).get("sid") or ""


def _windows() -> list[dict]:
    from gas_pult.tmux import Tmux
    try:
        return Tmux(config.load().session).windows()
    except (config.ConfigError, OSError):
        return []


def _window(ref: str) -> dict | None:
    """Окно по тому, как его называют люди: «@12» (id tmux), «13» (номер в строке tmux) или имя («gastech-site»)."""
    ref = str(ref or "").strip()
    ws = _windows()
    if ref.startswith("@"):
        return next((w for w in ws if w["id"] == ref), None)
    if ref.isdigit():
        return next((w for w in ws if str(w.get("idx")) == ref), None)
    same = [w for w in ws if w.get("name") == ref]
    return same[0] if len(same) == 1 else None


def _chat(ref: str) -> dict:
    """Поля чата задачи по ``--chat``; окна нет — понятная ошибка, а не молчание."""
    w = _window(ref)
    if not w:
        names = ", ".join(f"{x['idx']}:{x['name']}" for x in _windows()[:30]) or "окон нет"
        raise SystemExit(f"окно «{ref}» не найдено — укажите @id, номер или имя. Сейчас: {names}")
    return {"chat": w["id"], "sid": w.get("sid") or ""}


def cmd_notify(a):
    """Своё уведомление владельцам в бот — для агента («готово, нужен ваш ответ»). Ответ (reply) на него уйдёт
    в окно, из которого отправлено (``tgroutes``). Уровни уведомлений окна на него не действуют: это явная просьба.
    Приём — как ``bb push-notifications send`` (#189 п. 1)."""
    from gas_pult import tgroutes

    text = " ".join(a.text).strip() or (sys.stdin.read().strip() if not sys.stdin.isatty() else "")
    if not text:
        raise SystemExit("Текст уведомления пуст: gas-pult notify \"Готово, посмотрите\"")
    try:
        cfg = config.load()
    except config.ConfigError as e:
        raise SystemExit(str(e)) from None
    wid, name = (a.window, a.window) if a.window else own_window()
    head = f"🔔 [{name}] " if name else "🔔 "
    api, routes, sent = Api(cfg.token), tgroutes.Routes(cfg.data / "tg_routes.json"), 0
    for chat in cfg.owners:
        try:
            r = api("sendMessage", chat_id=chat, text=(head + text)[:3900])
        except TelegramError as e:
            print(f"не дошло до {chat}: {api.redact(e)}", file=sys.stderr)
            continue
        sent += 1
        if wid:
            routes.bind(chat, r.get("message_id"), wid)
    if not sent:
        raise SystemExit("уведомление не доставлено ни одному владельцу")
    print(f"отправлено владельцам: {sent}" + (f" · ответ придёт в окно {wid}" if wid else ""))


def cmd_last(a):
    print(transcripts.last_answer(os.path.abspath(a.path)) or "ответов не найдено")


def cmd_secrets(a):
    """Хуки скрытия секретов (``secrets_guard``) в папке Claude Code: поставить, убрать, проверить."""
    from gas_pult import secrets_guard

    d = Path(a.config_dir or os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()
    if a.action == "status":
        ok = secrets_guard.installed(d)
        print(f"Скрытие секретов в {d}: {'стоит' if ok else 'не стоит — gas-pult secrets install'}")
        raise SystemExit(0 if ok else 1)
    try:
        secrets_guard.install(d, python=a.python, remove=a.action == "uninstall")
    except ValueError as e:
        raise SystemExit(f"Ошибка: {e}") from None
    if a.action == "install":
        print("Новые сессии Claude Code в этой папке — со скрытием; открытые — после перезапуска.")


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
    s = sub.add_parser("asr", help="распознавание речи (T-one): install [--enable] | uninstall | status | check <файл>")
    s.add_argument("action", choices=["install", "uninstall", "status", "check"], nargs="?", default="status")
    s.add_argument("file", nargs="?", help="check — файл со звуком (ogg, wav, …)")
    s.add_argument("--enable", action="store_true", help="install — сразу включить и запустить службу")
    s.add_argument("--python", help="install — каким Python создать venv службы (по умолчанию этот)")
    s.add_argument("--model", help="install — готовый model.onnx вместо скачивания (проверяется sha256)")
    s.add_argument("--realtime", action="store_true", help="check — подавать звук в темпе речи, как микрофон")
    s.set_defaults(fn=cmd_asr)
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
    s = sub.add_parser("secrets", help="скрытие секретов от модели: install | uninstall | status [--config-dir …]")
    s.add_argument("action", choices=["install", "uninstall", "status"], nargs="?", default="status")
    s.add_argument("--config-dir", help="папка Claude Code (по умолчанию $CLAUDE_CONFIG_DIR или ~/.claude)")
    s.add_argument("--python", help="чем запускать хук (по умолчанию — этот Python)")
    s.set_defaults(fn=cmd_secrets)
    s = sub.add_parser("usage", help="функции панели: report — что не открывали 30 дней и что в ходу (файл и текст)")
    s.add_argument("action", choices=["report"], nargs="?", default="report")
    s.set_defaults(fn=cmd_usage)
    s = sub.add_parser("notify", help="своё уведомление владельцам в бот (агенту: «готово, нужен ответ»)")
    s.add_argument("text", nargs="*", help="текст; пусто — из stdin")
    s.add_argument("--window", default="", help="окно (@N), куда пойдёт ответ; по умолчанию — своё окно tmux")
    s.set_defaults(fn=cmd_notify)
    s = sub.add_parser("task", help="задачи владельца: add | list | done <id> | undo <id> | update <id> (#203)")
    s.add_argument("action", choices=["add", "list", "done", "undo", "update"])
    s.add_argument("id", nargs="?", default="")
    s.add_argument("--title", default="")
    s.add_argument("--type", default="", help="command | call | write | meeting | decision | check | other")
    s.add_argument("--next", default="", help="что сделать дальше — одна строка")
    s.add_argument("--status", default="", help="todo | doing | waiting | done (по умолчанию todo)")
    s.add_argument("--chat", default="",
                   help="окно задачи: @id, номер в tmux или имя; по умолчанию — своё; none — без чата")
    s.add_argument("--link", default="", help="источник: issue, PR, документ")
    s.add_argument("--cmd", default="", help="команда (тип command)")
    s.add_argument("--phone", default="", help="телефон (тип call)")
    s.add_argument("--to", default="", help="кому (тип write)")
    s.add_argument("--draft", default="", help="черновик сообщения (тип write)")
    s.add_argument("--with", dest="with_", default="", help="с кем встреча (тип meeting)")
    s.add_argument("--when", default="", help="когда (тип meeting)")
    s.add_argument("--question", default="", help="вопрос (тип decision)")
    s.add_argument("--option", action="append", help="вариант решения (тип decision), можно несколько")
    s.add_argument("--urgent", default="", help="срочно: yes | no")
    s.add_argument("--important", default="", help="важно: yes | no")
    s.add_argument("--q", default="", help="квадрант сразу: 1 срочно и важно · 2 важно · 3 срочно · 4 ни то ни другое")
    s.add_argument("--due", default="", help="срок ГГГГ-ММ-ДД (прошёл — задача станет срочной)")
    s.add_argument("--all", action="store_true", help="list: и выполненные")
    s.add_argument("--by", default="", help="кто поставил (по умолчанию «агент · окно»)")
    s.set_defaults(fn=cmd_task)
    s = sub.add_parser("last", help="последний ответ Claude в папке (текстом)")
    s.add_argument("path", nargs="?", default=".")
    s.set_defaults(fn=cmd_last)
    a = p.parse_args(argv)
    fn = getattr(a, "fn", None) or cmd_run
    if fn in (cmd_run, cmd_webapp):
        rogroup.regain()                               # группа pult-ro не дошла от systemd --user — получить её
    fn(a)
