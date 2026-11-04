"""Группа ``pult-ro`` у процессов пульта (задача 31): без неё пульт не читает журналы пространств и не видит их
процессы при ``hidepid``.

Беда: ``bin/pult-tenant-setup install`` добавляет владельца в ``pult-ro``, но менеджер ``systemd --user`` запущен
раньше и группу не получает — значит, и бот, и панель, перезапущенные им, остаются без неё. Перезапускать сам
``user@<uid>`` нельзя: он убьёт tmux с сессиями владельца.

Выход — запускать пульт через ``sg pult-ro -c …`` (shadow) или ``newgrp -c … pult-ro`` (util-linux; в Ubuntu 26.04 —
пакет ``util-linux-extra``). Обе программы меняют группу процесса без пароля, если пользователь записан в группе в
``/etc/group``. ``setpriv`` без прав root группу добавить не может.

- ``regain`` — в начале ``gas-pult run`` и ``gas-pult webapp``: группа есть в ``/etc/group``, владелец в ней, а у
  процесса её нет — один раз заменить процесс (тот же PID — systemd этого не замечает) на тот же запуск через
  обёртку. Сначала пробный ``id -G`` через обёртку: не вышло — пульт работает как раньше, без перезапусков по кругу.
- ``exec_start`` — строка ``ExecStart`` для ``gas-pult service install``: с обёрткой, когда группа есть, иначе
  как раньше.
- ``checks`` — для ``gas-pult doctor``: есть ли группа у работающих бота и панели.

Группы нет (пространства не настроены, macOS) — ничего не меняется.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from gas_pult.tenants import GROUP_RO

ENV = "GAS_PULT_RO"                       # уже перезапускались через обёртку — второй раз не пробовать
UNITS = ("gas-pult.service", "gas-pult-webapp.service")
TIMEOUT = 10
HINT_TOOL = "нет sg и newgrp с -c: sudo apt install util-linux-extra (Ubuntu 26.04+) или login (sg)"
HINT_RESTART = "systemctl --user restart gas-pult gas-pult-webapp — пульт сам запустится через обёртку"


def group(name: str = GROUP_RO):
    """Запись группы из /etc/group (``grp.struct_group``) или None — группы нет или это не Unix."""
    try:
        import grp
        return grp.getgrnam(name)
    except (ImportError, KeyError):
        return None


def me() -> str:
    import pwd
    return pwd.getpwuid(os.getuid()).pw_name


def member(g, user: str | None = None) -> bool:
    """Пользователь записан в группе (или она у него основная)."""
    if g is None:
        return False
    user = user or me()
    if user in g.gr_mem:
        return True
    import pwd
    try:
        return pwd.getpwnam(user).pw_gid == g.gr_gid
    except KeyError:
        return False


def has(gid: int) -> bool:
    """У этого процесса группа есть (дополнительная или действующая — после sg/newgrp)."""
    return gid in os.getgroups() or os.getegid() == gid


def proc_has(pid: int, gid: int, proc: str | Path = "/proc") -> bool | None:
    """Есть ли группа у процесса ``pid`` (по /proc/<pid>/status); процесса нет или не прочитать — None."""
    try:
        text = (Path(proc) / str(pid) / "status").read_text()
    except OSError:
        return None
    fields = dict(line.split(":", 1) for line in text.splitlines() if ":" in line)
    groups = fields.get("Groups", "").split()
    gids = fields.get("Gid", "").split()             # реальная, действующая, сохранённая, файловая
    return str(gid) in groups or str(gid) in gids[1:2] or str(gid) in gids[3:4]


def tool(which=shutil.which, runner=subprocess.run) -> tuple[str, str] | None:
    """Чем сменить группу: ("sg", путь) или ("newgrp", путь) — newgrp только из util-linux (у него есть -c)."""
    if p := which("sg"):
        return "sg", p
    if p := which("newgrp"):
        try:
            r = runner([p, "--version"], capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return None
        if "util-linux" in (r.stdout or "") + (r.stderr or ""):
            return "newgrp", p
    return None


def wrap(cmd: list[str], t: tuple[str, str], name: str = GROUP_RO) -> list[str]:
    """``cmd`` через обёртку: оболочка пользователя ``-c 'exec …'`` с группой ``name``."""
    line = "exec " + shlex.join(cmd)
    kind, path = t
    return [path, name, "-c", line] if kind == "sg" else [path, "-c", line, name]


def ready(name: str = GROUP_RO, which=shutil.which, runner=subprocess.run):
    """(группа, обёртка), если пульт должен работать с группой и может её получить; иначе (группа|None, None)."""
    g = group(name)
    if g is None or not member(g):
        return g, None
    return g, tool(which, runner)


def regain(argv: list[str] | None = None, env=None, execve=os.execve, runner=subprocess.run,
           which=shutil.which, log=None) -> str:
    """Перезапустить этот процесс с группой ``pult-ro``, если её нет. Возвращает, почему не перезапустил
    (при перезапуске не возвращается)."""
    env = os.environ if env is None else env
    log = log or (lambda m: print(m, file=sys.stderr, flush=True))
    if env.get(ENV):
        return "again"
    g = group()
    if g is None:
        return "no-group"
    if not member(g):
        return "not-member"
    if has(g.gr_gid):
        return "has"
    t = tool(which, runner)
    if t is None:
        log(f"gas-pult: у пульта нет группы {GROUP_RO} — журналы пространств не прочитать; {HINT_TOOL}")
        return "no-tool"
    try:
        probe = runner(wrap(["id", "-G"], t), capture_output=True, text=True, timeout=TIMEOUT,
                       stdin=subprocess.DEVNULL)
        ok = probe.returncode == 0 and str(g.gr_gid) in (probe.stdout or "").split()
    except (OSError, subprocess.SubprocessError):
        ok = False
    if not ok:
        log(f"gas-pult: {t[0]} не дал группу {GROUP_RO} — пульт работает без неё")
        return "failed"
    argv = argv or [sys.executable, "-m", "gas_pult", *sys.argv[1:]]
    cmd = wrap(argv, t)
    log(f"gas-pult: перезапуск с группой {GROUP_RO} через {t[0]}")
    execve(cmd[0], cmd, {**env, ENV: "1"})
    return "exec"                                      # только с подменённым execve (тесты)


# ---------- юнит systemd ----------
_PLAIN = re.compile(r"^[\w@+=:,./-]+$")


def sd_quote(arg: str) -> str:
    """Слово для ``ExecStart``: %, $ — удвоить; с пробелами и кавычками — в двойных кавычках."""
    s = arg.replace("%", "%%").replace("$", "$$")
    return s if _PLAIN.match(arg) else '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def exec_start(cmd: list[str], t: tuple[str, str] | None) -> str:
    return " ".join(sd_quote(a) for a in (wrap(cmd, t) if t else cmd))


# ---------- gas-pult doctor ----------
def main_pid(unit: str, runner=subprocess.run) -> int:
    try:
        r = runner(["systemctl", "--user", "show", "-p", "MainPID", "--value", unit], capture_output=True, text=True,
                   timeout=TIMEOUT)
        return int((r.stdout or "0").strip() or 0)
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0


def checks(runner=subprocess.run, which=shutil.which, proc: str | Path = "/proc") -> list[tuple[str, bool, str]]:
    """Строки для doctor: (что, хорошо ли, что сделать). Группы нет — пусто (пространства не настроены)."""
    g = group()
    if g is None:
        return []
    if not member(g):
        return [(f"группа {GROUP_RO}: вас в ней нет", False, "sudo bin/pult-tenant-setup install")]
    out = []
    t = tool(which, runner)
    out.append((f"обёртка группы {GROUP_RO}: " + (t[0] if t else "нет"), t is not None, HINT_TOOL))
    for unit in UNITS:
        pid = main_pid(unit, runner)
        if pid <= 0:
            continue
        ok = proc_has(pid, g.gr_gid, proc)
        name = unit.removesuffix(".service")
        if ok:
            out.append((f"{name}: группа {GROUP_RO} есть", True, ""))
        elif ok is False:
            out.append((f"у пульта нет группы {GROUP_RO} ({name}, PID {pid})", False,
                        HINT_RESTART if t else HINT_TOOL))
    return out
