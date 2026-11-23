"""Окно, порождённое из другого окна (владелец 23.11): агент в чате выносит задачу в новое окно сам —
``tmux new-window … -c <другая папка>``. Фокус-ссылка видит только окна своего проекта, и человек по ссылке нового окна
не находил. Теперь у такого окна есть родитель — опция окна ``@gas_pult_from`` (id окна, из которого его открыли), и
по ссылке видны окна, порождённые из её окон (``panel/focus.py``).

Как узнаём родителя. Пульт ставит в tmux владельца хук ``after-new-window`` (``install``): он запускает
``python -m gas_pult.spawned <окно> <сокет>`` и ждёт его (``run-shell`` без ``-b``). Пока хук работает, процесс
``tmux new-window`` ещё жив: в его окружении — ``TMUX_PANE`` панели, из которой его запустили (агент получил её от
своего окна), в аргументах — имя (``-n``) уже раскрытым оболочкой. Проверено на tmux 3.6 23.11: процесс клиента
«tmux: client» виден в /proc во время хука, ``TMUX_PANE`` — панель родителя.

Ограничения (честно):
- только окна, открытые командой ``tmux`` изнутри другого окна этого же сервера tmux; окно, открытое из пульта,
  бота, cron или по SSH без tmux, родителя не получает (у них нет ``TMUX_PANE``);
- два ``tmux new-window`` с одним именем в одну и ту же долю секунды из разных окон — родитель не ставится (неясно,
  чей);
- хук ставит работающий пульт; сервер tmux перезапустили — хук вернётся при следующем запуске пульта или новом окне
  из пульта (``Tmux.ensure_session``);
- пространства (свой сервер tmux у каждого) — хук не ставится: окно пространства по ссылке владельца не видно никогда;
- агент работает от того же пользователя, что и пульт, и может сам поставить опцию окну — это не новая граница:
  он и так видит всё, что видит пользователь.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

OPT = "@gas_pult_from"
HOOK = "after-new-window[73]"          # свой номер: чужие хуки after-new-window не затираем
PANE = re.compile(r"^%\d+$")
WIN = re.compile(r"^@\d+$")
SAFE = re.compile(r"^[A-Za-z0-9_./+-]+$")   # путь python и пакета — в команду хука без кавычек внутри кавычек
VERBS = ("new-window", "neww")


def _argv(pid: Path) -> list[str]:
    try:
        return [a.decode("utf-8", "replace") for a in pid.joinpath("cmdline").read_bytes().split(b"\0") if a]
    except OSError:
        return []


def _env(pid: Path) -> dict[str, str]:
    try:
        raw = pid.joinpath("environ").read_bytes()
    except OSError:
        return {}
    out = {}
    for kv in raw.split(b"\0"):
        k, eq, v = kv.decode("utf-8", "replace").partition("=")
        if eq:
            out[k] = v
    return out


def name_of(argv: list[str]) -> str | None:
    """Имя окна из аргументов ``tmux new-window``: ``-n имя`` или ``-nимя``; нет — None."""
    try:
        i = next(n for n, a in enumerate(argv) if a in VERBS)
    except StopIteration:
        return None
    rest = argv[i + 1:]
    for n, a in enumerate(rest):
        if a == "--":
            break
        if a == "-n" and n + 1 < len(rest):
            return rest[n + 1]
        if a.startswith("-n") and len(a) > 2:
            return a[2:]
    return None


def _same_socket(tmux_env: str, socket: str) -> bool:
    sock = tmux_env.split(",")[0]
    if not sock or not socket:
        return False
    return os.path.realpath(sock) == os.path.realpath(socket)


def clients(socket: str, proc: Path = Path("/proc")) -> list[tuple[str | None, str]]:
    """Живые ``tmux new-window`` этого пользователя к серверу ``socket``: [(имя окна из ``-n`` или None, панель
    ``TMUX_PANE``)] — только запущенные изнутри окна tmux (есть ``TMUX_PANE``)."""
    uid, out = os.getuid(), []
    try:
        pids = [p for p in proc.iterdir() if p.name.isdigit()]
    except OSError:
        return []
    for p in pids:
        try:
            if p.stat().st_uid != uid:
                continue
        except OSError:
            continue
        argv = _argv(p)
        if not argv or not os.path.basename(argv[0]).startswith("tmux") or not any(a in VERBS for a in argv):
            continue
        env = _env(p)
        pane = env.get("TMUX_PANE", "")
        if not PANE.match(pane) or not _same_socket(env.get("TMUX", ""), socket):
            continue
        out.append((name_of(argv), pane))
    return out


def parent_pane(socket: str, name: str, proc: Path = Path("/proc")) -> str:
    """Панель, из которой открыли окно с именем ``name``; не однозначно или нет — ""."""
    cs = clients(socket, proc)
    named = {pane for n, pane in cs if n is not None and n == name}
    if named:
        return named.pop() if len(named) == 1 else ""
    bare = {pane for n, pane in cs if n is None}        # без -n: имя tmux даёт сам — сверить не с чем
    return bare.pop() if len(bare) == 1 and len(cs) == 1 else ""


def _tmux(socket: str, *args: str) -> str:
    r = subprocess.run(["tmux", "-S", socket, *args], capture_output=True, text=True, timeout=5)
    return r.stdout.strip() if r.returncode == 0 else ""


def mark(wid: str, socket: str, proc: Path = Path("/proc")) -> str:
    """Хук: поставить новому окну ``wid`` родителя. Возвращает id окна-родителя или ""."""
    if not WIN.match(wid or "") or not socket:
        return ""
    name = _tmux(socket, "display-message", "-p", "-t", wid, "#{window_name}")
    pane = parent_pane(socket, name, proc)
    if not pane:
        return ""
    parent = _tmux(socket, "display-message", "-p", "-t", pane, "#{window_id}")
    if not WIN.match(parent) or parent == wid:
        return ""
    _tmux(socket, "set-option", "-w", "-t", wid, OPT, parent)
    return parent


def hook_command(python: str = sys.executable, pkg: str | None = None) -> str:
    """Команда хука для ``set-hook``; путь с необычными знаками — "" (хук не ставим, чем ломать кавычки).
    Вывод — в никуда: вывод ``run-shell`` tmux показал бы поверх окна, и Claude в нём перестал бы принимать ввод."""
    pkg = pkg or str(Path(__file__).resolve().parent.parent)
    if not SAFE.match(python) or not SAFE.match(pkg):
        return ""
    return (f'run-shell "PYTHONPATH={pkg} {python} -m gas_pult.spawned '
            "'#{window_id}' '#{socket_path}' >/dev/null 2>&1; true\"")


def install(run) -> bool:
    """Поставить хук на сервер tmux через ``run`` (``Tmux.run``). True — поставлен."""
    cmd = hook_command()
    if not cmd:
        return False
    run("set-hook", "-g", HOOK, cmd)
    return True


def main(argv: list[str]) -> int:
    if len(argv) >= 2:
        try:
            mark(argv[0], argv[1])
        except Exception:                 # хук не должен мешать открыть окно
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
