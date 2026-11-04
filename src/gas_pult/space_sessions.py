"""Сессии демо-пространства по-человечески (задача 32): своя папка, «Закрыть» / «Продолжить» / «Удалить» в корзину.

У каждой сессии пространства — своя папка ``home/projects/<имя>``: там её файлы, а журнал разговора Claude Code — в
``config/claude/projects/<папка>`` (его читает пульт через группу ``pult-ro``).

- **Закрыть** — агент выходит штатно, окно закрывается; папка и журнал остаются. Сессия — в списке «Закрытые».
- **Продолжить** — новое окно в той же папке: ``claude --continue`` (тот же разговор), черновик из поля ввода —
  обратно в поле.
- **Удалить** — папка сессии и её журнал уходят в корзину пространства ``trash/sessions/<время>__<папка>``;
  ``KEEP_DAYS`` дней их можно восстановить, потом — удаляются навсегда.

Пульт работает от своего пользователя и писать в пространство не может: все действия с папками — командой оболочки
от пользователя пространства, внутри его песочницы, через его tmux (``tmux run-shell``; ``sudo`` пускает только tmux).
Имена папок — только из ``folder_name``, в команду — через ``shlex.quote``.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import time
from pathlib import Path

from gas_pult import tenants, transcripts

KEEP_DAYS = 14
NAME_MAX = 60
TRASH = "sessions"                        # trash/sessions/<время>__<папка>
JOURNAL = ".journal"                      # журнал разговора внутри записи корзины
TRASH_ID = re.compile(r"^\d{8}-\d{6}__[^/\x00]+$")
DISK_FULL = "В пространстве закончилось место (лимит диска). Удалите лишние сессии или файлы — или попросите владельца."


def folder_name(name: str) -> str:
    """Имя сессии → имя папки: кириллица и пробелы можно; без «/», управляющих знаков и точки в начале."""
    s = re.sub(r"[\x00-\x1f\x7f/\\]+", " ", str(name or ""))
    s = re.sub(r"\s+", " ", s).strip().lstrip(".-~ ").strip()
    return s[:NAME_MAX].rstrip() or "сессия"


def sh(slug: str, script: str, timeout: int = 30) -> str:
    """Команда оболочки от пользователя пространства (в его песочнице). Ошибка — RuntimeError с понятным текстом."""
    tm = tenants.tmux_of(slug)
    tm.ensure_session()                                 # run-shell нужен работающий сервер tmux пространства
    try:
        r = subprocess.run([*tm.tmux, "run-shell", script + " 2>&1"], capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError("пространство не ответило вовремя — попробуйте ещё раз") from None
    out = r.stdout or ""
    if r.returncode != 0:
        if "No space left" in out or "Disk quota" in out:
            raise RuntimeError(DISK_FULL)
        tail = out.strip().splitlines()[-2:] if out.strip() else [r.stderr.strip()]
        raise RuntimeError("не вышло: " + " ".join(x for x in tail if x)[:300])
    return out


def projects(slug: str) -> Path:
    return tenants.paths(slug)["home"] / "projects"


def trash_dir(slug: str) -> Path:
    return tenants.paths(slug)["trash"] / TRASH


def create(slug: str, name: str) -> Path:
    """Новая папка сессии; занято — «имя 2», «имя 3»…"""
    base, root = folder_name(name), projects(slug)
    q = shlex.quote
    out = sh(slug, f"mkdir -p {q(str(root))} && cd {q(str(root))} && n={q(base)}; i=2; "
                   f'while [ -e "$n" ]; do n={q(base)}" $i"; i=$((i+1)); done; mkdir -- "$n" && printf "%s" "$n"')
    got = out.strip().splitlines()[-1] if out.strip() else ""
    if not got or "/" in got:
        raise RuntimeError("не вышло создать папку сессии")
    return root / got


def has_history(slug: str, path: Path | str) -> bool:
    return bool(transcripts.transcripts(str(path), tenants.paths(slug)["claude"]))


def listing(slug: str) -> list[dict]:
    """Папки сессий: [{folder, path, changed}] — самые свежие сверху."""
    root = projects(slug)
    out = sh(slug, f"cd {shlex.quote(str(root))} 2>/dev/null || exit 0; "
                   'for d in */; do [ -d "$d" ] && [ ! -L "${d%/}" ] && '
                   'printf "%s\\t%s\\n" "$(stat -c %Y -- "$d")" "${d%/}"; done; true')
    rows = []
    for line in out.splitlines():
        ts, _, name = line.partition("\t")
        if ts.isdigit() and name and folder_name(name) == name:
            rows.append({"folder": name, "path": str(root / name), "changed": int(ts)})
    return sorted(rows, key=lambda x: -x["changed"])


def open_paths(slug: str) -> set[str]:
    """Папки, где сейчас открыты окна, — во всех сессиях tmux пространства (не только в той, что видит панель:
    владелец мог открыть окно в пространстве сам). Такие папки не «закрытые»: их не продолжать и не удалять."""
    tm = tenants.tmux_of(slug)
    try:
        out = tm.run("list-windows", "-a", "-F", "#{pane_current_path}")
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def is_open(slug: str, path: Path | str) -> bool:
    """В папке (или глубже) работает окно."""
    p = str(path)
    return any(x == p or x.startswith(p + "/") for x in open_paths(slug))


def closed(slug: str, open_paths: set[str]) -> list[dict]:
    """Закрытые сессии: папки без открытого окна. ``history`` — есть ли разговор, который можно продолжить."""
    busy = lambda p: any(x == p or x.startswith(p + "/") for x in open_paths)     # noqa: E731
    return [{**x, "history": has_history(slug, x["path"])} for x in listing(slug) if not busy(x["path"])]


def check_folder(slug: str, folder: str) -> Path:
    """Папка сессии по имени — только прямо в ``projects`` (без «..», «/», точек в начале)."""
    if not folder or folder != folder_name(folder):
        raise ValueError("нет такой сессии")
    return projects(slug) / folder


def trash(slug: str, folder: str, now: float | None = None) -> dict:
    """«Удалить»: папка и журнал — в корзину пространства. Возвращает {id, until}."""
    src = check_folder(slug, folder)
    now = time.time() if now is None else now
    tid = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "__" + folder
    dst, jdir = trash_dir(slug) / tid, transcripts.project_dir(str(src), tenants.paths(slug)["claude"])
    q = shlex.quote
    sh(slug, f"[ -d {q(str(src))} ] && [ ! -L {q(str(src))} ] || {{ echo 'нет такой сессии'; exit 1; }}; "
             f"mkdir -p {q(str(trash_dir(slug)))} && mv -- {q(str(src))} {q(str(dst))} && "
             f"if [ -d {q(str(jdir))} ]; then mv -- {q(str(jdir))} {q(str(dst / JOURNAL))}; fi && "
             f"touch -- {q(str(dst))}")
    return {"id": tid, "until": int(now + KEEP_DAYS * 86400)}


def trash_list(slug: str, now: float | None = None) -> list[dict]:
    """Корзина: [{id, folder, deleted, until}]; записи старше ``KEEP_DAYS`` — удаляются навсегда здесь же."""
    now = time.time() if now is None else now
    d = shlex.quote(str(trash_dir(slug)))
    out = sh(slug, f"cd {d} 2>/dev/null || exit 0; find . -mindepth 1 -maxdepth 1 -type d -mtime +{KEEP_DAYS} "
                   "-exec rm -rf -- {} + ; "
                   'for x in */; do [ -d "$x" ] && printf "%s\\t%s\\n" "$(stat -c %Y -- "$x")" "${x%/}"; done; true')
    rows = []
    for line in out.splitlines():
        ts, _, tid = line.partition("\t")
        if ts.isdigit() and TRASH_ID.match(tid):
            rows.append({"id": tid, "folder": tid.split("__", 1)[1], "deleted": int(ts),
                         "until": int(ts) + KEEP_DAYS * 86400})
    return sorted(rows, key=lambda x: -x["deleted"])


def restore(slug: str, tid: str) -> str:
    """Вернуть из корзины: папка — обратно в ``projects`` (имя занято — «имя 2»), журнал — на место."""
    if not TRASH_ID.match(tid or "") or tid.split("__", 1)[1] != folder_name(tid.split("__", 1)[1]):
        raise ValueError("нет такой записи в корзине")
    src, base, root = trash_dir(slug) / tid, tid.split("__", 1)[1], projects(slug)
    q = shlex.quote
    out = sh(slug, f"[ -d {q(str(src))} ] || {{ echo 'нет такой записи в корзине'; exit 1; }}; mkdir -p {q(str(root))} "
                   f"&& cd {q(str(root))} && n={q(base)}; i=2; while [ -e \"$n\" ]; do n={q(base)}\" $i\"; i=$((i+1)); "
                   f"done; mv -- {q(str(src))} \"$n\" && printf '%s' \"$n\"")
    name = out.strip().splitlines()[-1]
    path, home = root / name, tenants.paths(slug)["claude"]
    jsrc, jdst = path / JOURNAL, transcripts.project_dir(str(path), home)
    sh(slug, f"if [ -d {q(str(jsrc))} ]; then mkdir -p {q(str(jdst.parent))} && "
             f"mv -- {q(str(jsrc))} {q(str(jdst))}; fi")
    return name
