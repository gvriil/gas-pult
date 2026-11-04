"""Скрипт владельца ``bin/pult-tenant``: создать, показать, сохранить и убрать демо-пространство (задача 25).

Запускает **владелец** через sudo — пульт этого не делает и не может (``docs/TENANTS.md``). Всё системное — через
``Sys``: команды и записи файлов печатаются, а с ``--dry-run`` только печатаются (так работают и тесты). Каждый шаг
идемпотентен: сначала проверка «уже сделано?», затем действие; повторный запуск чинит то, что сбилось.

Что делает ``create``: пользователь без входа в систему (nologin, без пароля), образ ext4 на пространство (лимит
диска), строка в /etc/fstab (с бэкапом) и монтирование, папки с правами (``tenants.LAYOUT``), slice systemd с
``MemoryMax``, ``CPUQuota``, ``TasksMax`` и служба с сервером tmux пространства в этом slice (песочница:
``ProtectHome``, ``ProtectProc=invisible``, ``ProtectSystem=strict``). Подписку владельца и его ``~/.claude`` не
трогает и не копирует. ``destroy`` — сначала бэкап, затем всё — в корзину; удалить совсем — отдельной командой
``purge`` со вторым подтверждением.
"""

from __future__ import annotations

import argparse
import getpass
import grp
import json
import os
import pwd
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from gas_pult import models, tenants
from gas_pult.tenants import GROUP_RO, GROUP_TENANTS, LAYOUT, LOGIN_WARNING

SIZE = re.compile(r"^(\d{1,4})([MG])$")
DEFAULT_SIZE = "2G"
LIMITS = {"MemoryMax": "1G", "CPUQuota": "80%", "TasksMax": "128"}
NOLOGIN = "/usr/sbin/nologin"


class Layout:
    """Где что лежит на сервере. Тесты подставляют временные папки."""

    def __init__(self, srv: Path = Path("/srv/pult"), etc: Path = Path("/etc")):
        self.srv, self.etc = Path(srv), Path(etc)
        self.tenants = self.srv / "tenants"
        self.images = self.srv / "images"
        self.backups = self.srv / "backups"
        self.trash = self.srv / "trash"
        self.etc_backup = self.srv / "etc-backup"
        self.systemd = self.etc / "systemd/system"
        self.fstab = self.etc / "fstab"

    def image(self, slug: str) -> Path:
        return self.images / f"{slug}.img"

    def units(self, slug: str) -> dict[str, Path]:
        """Юниты пространства: slice с лимитами, служба tmux, служба и таймер «журналы — группе пульта»."""
        u = tenants.user_of(slug)
        d = self.systemd
        return {"slice": d / f"{u}.slice", "service": d / f"{u}.service",
                "share": d / f"pult-share-{slug}.service", "timer": d / f"pult-share-{slug}.timer"}


class Sys:
    """Всё, что меняет систему. ``dry`` — только печать «что было бы»."""

    def __init__(self, dry: bool = False, out=print, runner=subprocess.run):
        self.dry, self.out, self.runner = dry, out, runner

    def run(self, *argv, check: bool = True, quiet: bool = False):
        argv = [str(a) for a in argv]
        if not quiet:
            self.out("$ " + shlex.join(argv))
        if self.dry:
            return None
        return self.runner(argv, check=check, capture_output=quiet, text=True)

    def read(self, *argv) -> str:
        """Команда только для чтения (systemctl is-active, df): выполняется и в сухом прогоне."""
        try:
            return self.runner([str(a) for a in argv], capture_output=True, text=True).stdout.strip()
        except OSError:
            return ""

    def write(self, path: Path, text: str, mode: int, user: str = "root", group: str = "root"):
        """Файл целиком (временный рядом и замена), сразу с нужными правами и владельцем."""
        if path.exists() and path.read_text(errors="replace") == text:
            self.fix(path, mode, user, group)
            return
        self.out(f"запись {path} ({mode:o} {user}:{group})")
        if self.dry:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        shutil.chown(tmp, user, group)
        os.chmod(tmp, mode)
        os.replace(tmp, path)

    def append(self, path: Path, line: str):
        self.out(f"дописать в {path}: {line.strip()}")
        if not self.dry:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)

    def mkdir(self, path: Path, mode: int, user: str = "root", group: str = "root"):
        if not path.is_dir():
            self.out(f"папка {path} ({mode:o} {user}:{group})")
            if self.dry:
                return
            path.mkdir(parents=True, exist_ok=True)
        self.fix(path, mode, user, group)

    def fix(self, path: Path, mode: int, user: str, group: str):
        if self.dry and not path.exists():
            return
        st = path.stat()
        want_u, want_g = _uid(user), _gid(group)
        if (st.st_mode & 0o7777) == mode and (want_u is None or st.st_uid == want_u) and \
                (want_g is None or st.st_gid == want_g):
            return
        self.out(f"права {path}: {mode:o} {user}:{group}")
        if not self.dry:
            shutil.chown(path, user, group)
            os.chmod(path, mode)

    def move(self, src: Path, dst: Path):
        self.out(f"перенести {src} → {dst}")
        if not self.dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))


def _uid(user: str) -> int | None:
    try:
        return pwd.getpwnam(user).pw_uid
    except KeyError:
        return None


def _gid(group: str) -> int | None:
    try:
        return grp.getgrnam(group).gr_gid
    except KeyError:
        return None


def user_exists(user: str) -> bool:
    return _uid(user) is not None


def mounted(path: Path, mountinfo: Path = Path("/proc/self/mountinfo")) -> bool:
    try:
        lines = mountinfo.read_text().splitlines()
    except OSError:
        return False
    p = str(path).rstrip("/")
    return any(len(f := line.split()) > 4 and f[4].replace("\\040", " ") == p for line in lines)


def check_size(size: str) -> str:
    m = SIZE.match(str(size or "").upper())
    if not m or int(m.group(1)) == 0 or (m.group(2) == "G" and int(m.group(1)) > 512):
        raise ValueError("размер диска — например 2G или 500M (до 512G)")
    return m.group(0)


def fstab_line(lay: Layout, slug: str) -> str:
    # nofail: битый образ не остановит загрузку сервера; nodev, nosuid — в пространстве нет устройств и suid
    return f"{lay.image(slug)} {lay.tenants / slug} ext4 loop,nodev,nosuid,nofail 0 2\n"


def slice_unit(slug: str, limits: dict | None = None) -> str:
    lim = {**LIMITS, **(limits or {})}
    return (f"# gas-pult: лимиты пространства {slug}. Создано pult-tenant; откат — pult-tenant destroy {slug}\n"
            f"[Unit]\nDescription=gas-pult: пространство {slug}\n\n[Slice]\n"
            + "".join(f"{k}={v}\n" for k, v in lim.items()))


def service_unit(lay: Layout, slug: str, tmux: str) -> str:
    """Сервер tmux пространства (``tmux -D``: не уходит в фон и не выходит без сессий). Окна, которые пульт открывает
    через сокет, — его дети: они в slice пространства и в его песочнице.

    ``RestrictSUIDSGID`` здесь нет: его фильтр seccomp запрещает ``openat2`` целиком (ENOSYS), а GNU tar 1.35 открывает
    им файлы во вложенных папках архива — «Cannot open: Function not implemented», агент не распаковывает архивы.
    suid/sgid и так не дают прав: образ смонтирован ``nosuid``, у службы ``NoNewPrivileges=yes``."""
    p = tenants.paths(slug, lay.tenants)
    u = tenants.user_of(slug)
    env = {"HOME": p["home"], "TMPDIR": p["tmp"], "CLAUDE_CONFIG_DIR": p["claude"], "SHELL": "/bin/bash",
           "PATH": tenants.path_env(slug, lay.tenants), "LANG": "C.UTF-8"}
    return (f"# gas-pult: tmux пространства {slug}. Создано pult-tenant; откат — pult-tenant destroy {slug}\n"
            f"[Unit]\nDescription=gas-pult: tmux пространства {slug}\nRequiresMountsFor={p['base']}\n\n"
            f"[Service]\nType=simple\nUser={u}\nGroup={u}\nSlice={u}.slice\nUMask=0027\n"
            f"WorkingDirectory={p['home']}\n"
            + "".join(f"Environment={shlex.quote(f'{k}={v}')}\n" for k, v in env.items())
            + f"ExecStart={tmux} -D -f /dev/null -S {p['socket']}\n"
            "Restart=always\nRestartSec=3\n"
            "NoNewPrivileges=yes\nPrivateTmp=yes\nProtectHome=yes\nProtectProc=invisible\nProtectSystem=strict\n"
            f"ReadWritePaths={p['base']}\nProtectKernelTunables=yes\nProtectKernelModules=yes\n"
            "ProtectControlGroups=yes\nLockPersonality=yes\n\n"
            "[Install]\nWantedBy=multi-user.target\n")


def share_units(lay: Layout, slug: str) -> tuple[str, str]:
    """Claude Code пишет журналы 0600 — группа пульта их не прочтёт. Раз в 30 секунд пользователь пространства сам
    открывает группе ``pult-ro`` чтение новых журналов (только в ``config/claude/projects``; папка — setgid pult-ro)."""
    p = tenants.paths(slug, lay.tenants)
    u, proj = tenants.user_of(slug), p["config_claude_projects"]
    service = (f"# gas-pult: журналы пространства {slug} — на чтение пульту. Создано pult-tenant\n"
               f"[Unit]\nDescription=gas-pult: журналы {slug} — группе {GROUP_RO}\nRequiresMountsFor={p['base']}\n\n"
               f"[Service]\nType=oneshot\nUser={u}\nGroup={u}\nSlice={u}.slice\nNoNewPrivileges=yes\n"
               f"ExecStart=/usr/bin/find {proj} ( -type d ! -perm -g=rx -exec chmod g+rx {{}} + ) -o "
               f"( -type f ! -perm -g=r -exec chmod g+r {{}} + )\n")
    timer = (f"# gas-pult: см. pult-share-{slug}.service\n[Unit]\nDescription=gas-pult: журналы {slug} — пульту\n\n"
             "[Timer]\nOnBootSec=1min\nOnUnitActiveSec=30s\nAccuracySec=5s\n\n[Install]\nWantedBy=timers.target\n")
    return service, timer


def meta_of(old: dict | None, slug: str, title=None, jurisdiction=None, persona=None, profile=None) -> dict:
    """Описание пространства: старое + то, что передали явно; всё проверено. Профиль по умолчанию — с ключом API."""
    m = dict(old or {})
    if title is not None:
        m["title"] = " ".join(str(title).split())[:60]
    m.setdefault("title", slug)
    if jurisdiction is not None:
        m["jurisdiction"] = tenants.check_jurisdiction(jurisdiction)
    m.setdefault("jurisdiction", "")
    m["persona"] = tenants.check_persona(persona or m.get("persona") or tenants.DEFAULT_PERSONA)
    prof = profile or m.get("profile")
    if prof and prof != "claude" and prof not in tenants.api_profiles(m["jurisdiction"]):
        if profile:                              # явно попросили неподходящий — ошибка
            tenants.check_profile(prof, m["jurisdiction"])
        prof = None                              # сменилась юрисдикция — профиль по умолчанию для новой
    if prof == "claude" and not m.get("claude_login"):
        tenants.check_profile(prof, m["jurisdiction"])
    m["profile"] = prof or tenants.default_profile(m["jurisdiction"])
    m.setdefault("created", time.strftime("%Y-%m-%dT%H:%M:%S"))
    return m


def audit(s: Sys, p: dict, event: str, **extra):
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, "by": os.environ.get("SUDO_USER", ""), **extra}
    if p["audit"].parent.is_dir():
        s.append(p["audit"], json.dumps(rec, ensure_ascii=False) + "\n")


def backup_file(s: Sys, lay: Layout, f: Path) -> Path:
    s.mkdir(lay.etc_backup, 0o700)
    dst = lay.etc_backup / f"{f.name}.{time.strftime('%Y%m%d-%H%M%S')}"
    s.out(f"бэкап {f} → {dst}")
    if not s.dry:
        shutil.copy2(f, dst)
    return dst


def need_setup(lay: Layout, s: Sys):
    if not tenants.marker(lay.tenants):
        msg = "не сделана настройка: сначала sudo bin/pult-tenant-setup install (docs/TENANTS.md, шаг 1)"
        if not s.dry:
            raise SystemExit(msg)
        s.out("(сухой прогон) " + msg)


def create(lay: Layout, s: Sys, slug: str, title=None, jurisdiction=None, persona=None, profile=None,
           budget: float | None = None, size: str = DEFAULT_SIZE) -> dict:
    slug, size = tenants.check_slug(slug), check_size(size)
    need_setup(lay, s)
    p = tenants.paths(slug, lay.tenants)
    u = tenants.user_of(slug)
    old = tenants.load(slug, lay.tenants)
    meta = meta_of(old, slug, title, jurisdiction, persona, profile)
    if budget is not None and not 0 <= float(budget) <= 1000:
        raise ValueError("бюджет — от 0 до 1000 USD в день")
    tmux = tenants.tmux_bin(lay.tenants)
    s.out(f"== пространство {slug}: пользователь {u}, диск {size}, профиль {meta['profile']}")

    # 1. пользователь без входа в систему: nologin, без пароля, без своей группы входа у других
    if user_exists(u):
        s.out(f"✓ пользователь {u} уже есть")
    else:
        s.run("useradd", "--system", "--user-group", "--groups", GROUP_TENANTS, "--home-dir", p["home"],
              "--no-create-home", "--shell", NOLOGIN, "--comment", f"gas-pult tenant {slug}", u)
    # 2. образ ext4 — дисковый лимит
    img = lay.image(slug)
    s.mkdir(lay.images, 0o700)
    if img.exists():
        s.out(f"✓ образ {img} уже есть")
    else:
        s.run("fallocate", "-l", size, img)
        s.run("chmod", "600", img)
        s.run("mkfs.ext4", "-q", "-F", "-m", "0", img)
    # 3. точка монтирования, строка в fstab (с бэкапом), монтирование
    s.mkdir(lay.tenants, 0o751, "root", GROUP_RO)
    if not mounted(p["base"]):
        s.mkdir(p["base"], 0o700)
    line = fstab_line(lay, slug)
    fstab = lay.fstab.read_text() if lay.fstab.exists() else ""
    if any(ln.split()[:1] == [str(img)] for ln in fstab.splitlines()):
        s.out(f"✓ {img} уже в {lay.fstab}")
    else:
        if lay.fstab.exists():
            backup_file(s, lay, lay.fstab)
        s.append(lay.fstab, line)
        s.run("systemctl", "daemon-reload")
    if mounted(p["base"]):
        s.out(f"✓ {p['base']} смонтирован")
    else:
        s.run("mount", p["base"])
    # 4. папки и файлы с правами
    if p["base"].exists():
        s.fix(p["base"], 0o710, u, GROUP_RO)
    for rel, (mode, group) in LAYOUT.items():
        s.mkdir(p["base"] / rel, mode, u, u if group == "own" else group)
    if not p["secrets"].exists():
        s.write(p["secrets"], "{}\n", 0o600, u, u)
    else:
        s.fix(p["secrets"], 0o600, u, u)
    if not p["audit"].exists():
        s.write(p["audit"], "", 0o640, "root", GROUP_RO)
    budget_old = (old or {}).get("budget_usd")
    daily = float(budget) if budget is not None else (budget_old if budget_old is not None else tenants.DEFAULT_BUDGET)
    s.write(p["budget"], json.dumps({"daily_usd": daily}) + "\n", 0o640, "root", GROUP_RO)
    s.write(p["meta"], json.dumps({k: v for k, v in meta.items() if k not in ("slug", "budget_usd")},
                                  ensure_ascii=False, indent=1) + "\n", 0o644)
    # 5. slice с лимитами, служба tmux пространства, таймер «журналы — группе пульта»
    un = lay.units(slug)
    s.write(un["slice"], slice_unit(slug), 0o644)
    unit = service_unit(lay, slug, tmux)
    changed = un["service"].exists() and un["service"].read_text(errors="replace") != unit
    s.write(un["service"], unit, 0o644)
    share, timer = share_units(lay, slug)
    s.write(un["share"], share, 0o644)
    s.write(un["timer"], timer, 0o644)
    s.run("systemctl", "daemon-reload")
    s.run("systemctl", "enable", "--now", un["service"].name, un["timer"].name)
    if changed:                                         # работающая служба живёт по старому юниту до перезапуска
        s.out(f"! Служба пространства изменилась. Перезапустите её, когда в окнах никто не работает: sudo systemctl "
              f"restart {un['service'].name}. Окна закроются; история разговоров и файлы остаются — сессии "
              "продолжаются кнопкой «Продолжить».")
    audit(s, p, "update" if old else "create", profile=meta["profile"], size=size)
    s.out(f"Готово: {slug}. Ключ модели — sudo bin/pult-tenant key {slug} {meta['profile']} (ключ — со стандартного "
          f"ввода). Проверка изоляции — sudo bin/pult-tenant check {slug} <другое>.")
    return meta


def backup(lay: Layout, s: Sys, slug: str) -> Path:
    """Архив папки пространства (без tmp и run) в ``/srv/pult/backups``, 0600, с числовыми владельцами и ACL."""
    slug = tenants.check_slug(slug)
    p = tenants.paths(slug, lay.tenants)
    if not p["base"].is_dir():
        raise SystemExit(f"нет папки пространства {p['base']}")
    s.mkdir(lay.backups, 0o700)
    dst = lay.backups / f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
    s.run("tar", "--numeric-owner", "--acls", "-czf", dst, "-C", p["base"], "--exclude=./tmp", "--exclude=./run",
          "--exclude=./lost+found", ".")
    s.run("chmod", "600", dst)
    audit(s, p, "backup", file=str(dst))
    s.out(f"Бэкап: {dst}")
    return dst


def confirm(given: str | None, want: str, prompt: str) -> bool:
    if given is not None:
        return given == want
    if not sys.stdin.isatty():
        return False
    return input(prompt).strip() == want


def destroy(lay: Layout, s: Sys, slug: str, yes: str | None = None) -> Path | None:
    """Убрать пространство: бэкап → служба стоп → размонтировать → fstab (с бэкапом) → образ и юниты в корзину →
    пользователь заблокирован. Ничего не удаляется: вернуть — docs/TENANTS.md, удалить совсем — ``purge``."""
    slug = tenants.check_slug(slug)
    if not confirm(yes, slug, f"Убрать пространство {slug} в корзину? Введите его имя: "):
        raise SystemExit("Не подтверждено — ничего не сделано (нужно --yes <имя пространства>).")
    p = tenants.paths(slug, lay.tenants)
    u = tenants.user_of(slug)
    arch = backup(lay, s, slug) if p["base"].is_dir() and (mounted(p["base"]) or s.dry) else None
    if arch is None:
        s.out("! папка пространства не смонтирована — бэкапа нет; образ уйдёт в корзину целиком")
    audit(s, p, "destroy", backup=str(arch or ""))
    entry = lay.trash / f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}"
    s.mkdir(lay.trash, 0o700)
    s.mkdir(entry, 0o700)
    un = lay.units(slug)
    s.run("systemctl", "disable", "--now", un["service"].name, un["timer"].name, check=False)
    if mounted(p["base"]):
        s.run("umount", p["base"])
    img = lay.image(slug)
    if lay.fstab.exists() and any(ln.split()[:1] == [str(img)] for ln in lay.fstab.read_text().splitlines()):
        backup_file(s, lay, lay.fstab)
        keep = "".join(ln for ln in lay.fstab.read_text().splitlines(keepends=True) if ln.split()[:1] != [str(img)])
        s.write(lay.fstab, keep, 0o644)
    for f in (img, *un.values()):
        if f.exists():
            s.move(f, entry / f.name)
    s.run("systemctl", "daemon-reload")
    if p["base"].is_dir() and not mounted(p["base"]):
        s.run("rmdir", p["base"], check=False)
    if user_exists(u):
        s.run("usermod", "--lock", "--expiredate", "1", u)
    s.write(entry / "info.json", json.dumps({"slug": slug, "user": u, "backup": str(arch or ""),
                                             "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n",
            0o600)
    s.out(f"Пространство {slug} — в корзине: {entry}. Бэкап: {arch or '—'}.\n"
          f"Удалить совсем (необратимо): sudo bin/pult-tenant purge {entry.name} --yes {slug}")
    return entry


def purge(lay: Layout, s: Sys, name: str, yes: str | None = None):
    """Удалить из корзины навсегда: папку корзины и пользователя. Второе подтверждение — имя пространства."""
    entry = lay.trash / name
    if "/" in name or name.startswith(".") or not entry.is_dir():
        raise SystemExit(f"нет такой записи в корзине: {name} (список — pult-tenant list)")
    try:
        info = json.loads((entry / "info.json").read_text())
        slug = tenants.check_slug(info["slug"])
    except (OSError, ValueError, KeyError) as e:
        raise SystemExit(f"не читается {entry}/info.json: {e}") from None
    if not confirm(yes, slug, f"НАВСЕГДА удалить {name} и пользователя? Введите имя пространства ещё раз: "):
        raise SystemExit("Не подтверждено — ничего не удалено (нужно --yes <имя пространства>).")
    u = tenants.user_of(slug)
    if (lay.tenants / slug).exists():
        s.out(f"! пространство {slug} создано заново — пользователя {u} не удаляю")
    elif user_exists(u):
        s.run("userdel", u)
    s.run("rm", "-rf", "--one-file-system", entry)
    s.out(f"Удалено: {entry}. Бэкап {info.get('backup') or '—'} остался — удалите его сами, если не нужен.")


def listing(lay: Layout, s: Sys) -> list[dict]:
    rows = []
    for slug in tenants.slugs(lay.tenants):
        t = tenants.load(slug, lay.tenants) or {}
        p = tenants.paths(slug, lay.tenants)
        sv = lay.units(slug)["service"]
        used = s.read("df", "--output=pcent", p["base"]).splitlines()[-1:] if mounted(p["base"]) else []
        rows.append({"slug": slug, "user": tenants.user_of(slug), "mounted": mounted(p["base"]),
                     "service": s.read("systemctl", "is-active", sv.name) or "?", "disk": "".join(used).strip(),
                     "profile": t.get("profile", ""), "jurisdiction": t.get("jurisdiction", ""),
                     "budget": t.get("budget_usd")})
    s.out("Включено (настройка сделана)" if tenants.enabled(lay.tenants) else "Выключено: нет настройки")
    for r in rows:
        s.out(f"{r['slug']:<24} {r['user']:<31} смонтирован={'да' if r['mounted'] else 'нет'} "
              f"tmux={r['service']} диск={r['disk'] or '—'} профиль={r['profile'] or '—'} "
              f"юрисдикция={r['jurisdiction'] or '—'} бюджет={r['budget']}")
    if lay.trash.is_dir():
        for e in sorted(os.listdir(lay.trash)):
            s.out(f"корзина: {e}")
    return rows


def set_key(lay: Layout, s: Sys, slug: str, profile: str, key: str, base_url: str = "", default: bool = False):
    """Ключ API профиля — в ``secrets.json`` пространства и в его файл настроек ``config/profiles/<id>.json``
    (оба 0600, владелец — пользователь пространства). Ключи пульта и подписка владельца не используются."""
    slug = tenants.check_slug(slug)
    t = tenants.load(slug, lay.tenants)
    if not t:
        raise SystemExit(f"нет пространства {slug}")
    tenants.check_profile(profile, t.get("jurisdiction", ""))     # «claude» сюда не попадёт: у него нет ключа
    key = key.strip()
    if not key or len(key) > 400 or any(c.isspace() for c in key):
        raise ValueError("ключ — одна строка без пробелов")
    p = tenants.paths(slug, lay.tenants)
    u = tenants.user_of(slug)
    prof = models.BY_ID[profile]
    state = {}
    if prof.get("gateway"):
        url = models.check_url(base_url)
        if not url:
            raise ValueError(f"у {prof['title']} нужен адрес шлюза: --base-url https://…")
        state = {"model_profiles": {profile: {"base_url": url}}}
    try:
        secrets = json.loads(p["secrets"].read_text()) if p["secrets"].exists() else {}
    except ValueError:
        secrets = {}
    secrets[prof["key"]] = key
    s.write(p["secrets"], json.dumps(secrets, indent=1) + "\n", 0o600, u, u)
    s.write(p["config_profiles"] / f"{profile}.json",
            json.dumps({"env": models.env_of(prof, key, state)}, ensure_ascii=False) + "\n", 0o600, u, u)
    if default:
        meta = meta_of(t, slug, profile=profile)
        s.write(p["meta"], json.dumps({k: v for k, v in meta.items() if k not in ("slug", "budget_usd")},
                                      ensure_ascii=False, indent=1) + "\n", 0o644)
    audit(s, p, "key", profile=profile, tail=key[-4:])


def login(lay: Layout, s: Sys, slug: str, yes: str | None = None):
    """Разрешить профиль «claude» в пространстве — после того, как владелец сам войдёт в Claude внутри него.
    Ничего не копирует: вход — вручную, ``/login`` в окне пространства."""
    slug = tenants.check_slug(slug)
    t = tenants.load(slug, lay.tenants)
    if not t:
        raise SystemExit(f"нет пространства {slug}")
    j = t.get("jurisdiction", "")
    if j and not models.allowed("claude", j):
        raise SystemExit(f"Claude недоступен для юрисдикции {j} — только профили: {', '.join(tenants.api_profiles(j))}")
    s.out("ВНИМАНИЕ. " + LOGIN_WARNING)
    if not confirm(yes, "да", "Это только для ваших тестов? Введите «да»: "):
        raise SystemExit("Не подтверждено — ничего не сделано (нужно --yes да).")
    p = tenants.paths(slug, lay.tenants)
    meta = {k: v for k, v in t.items() if k not in ("slug", "budget_usd")} | {
        "claude_login": True, "claude_login_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    s.write(p["meta"], json.dumps(meta, ensure_ascii=False, indent=1) + "\n", 0o644)
    audit(s, p, "claude_login")
    sock, u = p["socket"], tenants.user_of(slug)
    s.out(f"Теперь войдите сами, в своём терминале: sudo -u {u} {tenants.tmux_bin(lay.tenants)} -S {sock} "
          f"new-session -A -s login claude — и /login в окне (выйти из окна: Ctrl-b d). Отменить: "
          f"sudo bin/pult-tenant logout {slug}.")


def logout(lay: Layout, s: Sys, slug: str):
    slug = tenants.check_slug(slug)
    t = tenants.load(slug, lay.tenants)
    if not t:
        raise SystemExit(f"нет пространства {slug}")
    p = tenants.paths(slug, lay.tenants)
    meta = {k: v for k, v in t.items() if k not in ("slug", "budget_usd", "claude_login", "claude_login_at")}
    if meta.get("profile") == "claude":
        meta["profile"] = tenants.default_profile(meta.get("jurisdiction", ""))
    s.write(p["meta"], json.dumps(meta, ensure_ascii=False, indent=1) + "\n", 0o644)
    cred = p["claude"] / ".credentials.json"
    if cred.exists():
        s.run("rm", "-f", cred)
    audit(s, p, "claude_logout")
    s.out(f"Вход в Claude в {slug} выключен; профиль — {meta['profile']}.")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pult-tenant", description="Демо-пространства gas-pult (запускать через sudo). "
                                 "Подробно — docs/TENANTS.md.")
    ap.add_argument("--dry-run", action="store_true", help="только показать, что будет сделано")
    ap.add_argument("--srv", default="/srv/pult", help=argparse.SUPPRESS)
    ap.add_argument("--etc", default="/etc", help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="создать пространство (повторно — починить и обновить описание)")
    c.add_argument("slug")
    c.add_argument("--title")
    c.add_argument("--jurisdiction", help="страна клиента: RU — только российские профили")
    c.add_argument("--persona", help=f"вид панели по умолчанию ({', '.join(tenants.personas.PERSONAS)})")
    c.add_argument("--profile", help="профиль модели (по умолчанию — первый с ключом API для юрисдикции)")
    c.add_argument("--budget", type=float, help=f"USD в день (по умолчанию {tenants.DEFAULT_BUDGET})")
    c.add_argument("--size", default=DEFAULT_SIZE, help="диск пространства (по умолчанию 2G)")
    sub.add_parser("list", help="пространства, их состояние и корзина")
    b = sub.add_parser("backup", help="архив пространства в /srv/pult/backups")
    b.add_argument("slug")
    d = sub.add_parser("destroy", help="бэкап и перенос в корзину (не удаляет)")
    d.add_argument("slug")
    d.add_argument("--yes", metavar="ИМЯ", help="подтверждение: имя пространства")
    pg = sub.add_parser("purge", help="удалить запись корзины навсегда (второе подтверждение)")
    pg.add_argument("entry")
    pg.add_argument("--yes", metavar="ИМЯ", help="подтверждение: имя пространства")
    k = sub.add_parser("key", help="ключ API профиля для пространства (ключ — со стандартного ввода)")
    k.add_argument("slug")
    k.add_argument("profile", choices=[p["id"] for p in models.PROFILES if p.get("key")])
    k.add_argument("--base-url", default="", help="адрес шлюза (GigaChat, YandexGPT)")
    k.add_argument("--default", action="store_true", help="сделать профилем пространства по умолчанию")
    lg = sub.add_parser("login", help="разрешить ручной вход в Claude — только для ваших тестов")
    lg.add_argument("slug")
    lg.add_argument("--yes", metavar="да")
    lo = sub.add_parser("logout", help="выключить вход в Claude в пространстве")
    lo.add_argument("slug")
    ck = sub.add_parser("check", help="автотест изоляции: из A — к файлам, процессам и tmux B и к ~владельца")
    ck.add_argument("a")
    ck.add_argument("b")
    ck.add_argument("--owner", help="пользователь пульта (по умолчанию — тот, кто запустил sudo)")
    return ap


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    lay, s = Layout(Path(a.srv), Path(a.etc)), Sys(dry=a.dry_run)
    if a.cmd not in ("list",) and not a.dry_run and os.geteuid() != 0:
        print("Нужны права root: sudo bin/pult-tenant … (или --dry-run — только показать шаги)", file=sys.stderr)
        return 2
    os.umask(0o077)
    try:
        if a.cmd == "create":
            create(lay, s, a.slug, a.title, a.jurisdiction, a.persona, a.profile, a.budget, a.size)
        elif a.cmd == "list":
            listing(lay, s)
        elif a.cmd == "backup":
            backup(lay, s, a.slug)
        elif a.cmd == "destroy":
            destroy(lay, s, a.slug, a.yes)
        elif a.cmd == "purge":
            purge(lay, s, a.entry, a.yes)
        elif a.cmd == "key":
            key = sys.stdin.readline() if not sys.stdin.isatty() else getpass.getpass("Ключ (не отображается): ")
            set_key(lay, s, a.slug, a.profile, key, a.base_url, a.default)
        elif a.cmd == "login":
            login(lay, s, a.slug, a.yes)
        elif a.cmd == "logout":
            logout(lay, s, a.slug)
        elif a.cmd == "check":
            from gas_pult import tenant_check
            return tenant_check.main(lay.tenants, a.a, a.b, a.owner)
    except ValueError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as e:
        print(f"Ошибка: команда {shlex.join(e.cmd)} вернула {e.returncode}. Повторный запуск продолжит с этого шага.",
              file=sys.stderr)
        return 1
    return 0
