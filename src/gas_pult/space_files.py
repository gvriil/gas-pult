"""Файлы сессии демо-пространства (задача 32, п. 4): загрузить, посмотреть список, скачать.

Пульт не пишет и не читает пространство сам. Файл идёт через буфер tmux сервера пространства:
- **загрузка** — ``load-buffer -`` (байты со стандартного ввода) → ``save-buffer <путь>``;
- **скачивание** — ``load-buffer <путь>`` → ``save-buffer -``.

Обе операции выполняет клиент tmux от пользователя пространства (``sudo -u … tmux``), то есть с его правами. Путь
проверяется до операции командой оболочки в песочнице пространства. Он должен быть внутри папки сессии: без ``..``,
без абсолютных путей, ``realpath`` (симлинки раскрыты) — под папкой.

Имена файлов — с кириллицей; занято — «имя (2).ext». Место на диске пространства (образ, по умолчанию 2 ГБ)
проверяется до загрузки, а «No space left» при записи даёт понятный текст.
"""

from __future__ import annotations

import re
import secrets
import shlex
import subprocess
from pathlib import Path

from gas_pult import tenants
from gas_pult.space_sessions import DISK_FULL, sh

FILE_MAX = 50 << 20                       # как у загрузки в панели
LIST_MAX = 300
NAME_MAX = 120
SKIP = (".claude/", ".git/", "node_modules/", ".journal/")


def file_name(name: str) -> str:
    """Имя загружаемого файла: только последняя часть пути; без управляющих знаков и точки в начале."""
    s = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lstrip(".-~ ").strip()
    if len(s) > NAME_MAX:
        stem, dot, ext = s.rpartition(".")
        s = (stem[:NAME_MAX - len(ext) - 1] + "." + ext) if dot and len(ext) <= 10 else s[:NAME_MAX]
    return s or "файл"


def folder_of(slug: str, w: dict) -> Path:
    """Папка сессии окна — только внутри домашней папки пространства."""
    home = tenants.paths(slug)["home"]
    p = Path(w.get("path") or "")
    if w.get("space") != slug or not (p == home or home in p.parents):
        raise LookupError("окна уже нет")
    return p


def check_rel(rel: str) -> str:
    """Путь файла относительно папки сессии: без абсолютных путей и «..»."""
    rel = str(rel or "").replace("\\", "/").strip()
    parts = [x for x in rel.split("/") if x not in ("", ".")]
    if not parts or rel.startswith("/") or ".." in parts or "\x00" in rel:
        raise ValueError("файл — только из папки этой сессии")
    return "/".join(parts)


def _tmux(slug: str, *args: str, data: bytes | None = None, timeout: int = 120) -> bytes:
    tm = tenants.tmux_of(slug)
    r = subprocess.run([*tm.tmux, *args], input=data, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or b"").decode(errors="replace")
        if "No space left" in err or "Disk quota" in err:
            raise RuntimeError(DISK_FULL)
        raise RuntimeError("не вышло: " + err.strip()[:200])
    return r.stdout


def listing(slug: str, folder: Path) -> dict:
    """Файлы папки сессии (до трёх уровней, без служебных папок) и свободное место пространства."""
    q = shlex.quote(str(folder))
    out = sh(slug, f"cd {q} || exit 3; df -B1 --output=avail . | tail -1; "
                   f"find . -maxdepth 3 -type f -printf '%s\\t%T@\\t%P\\n' | head -n {LIST_MAX * 3}")
    lines = out.splitlines()
    free = int(lines[0].strip()) if lines and lines[0].strip().isdigit() else None
    files = []
    for line in lines[1:]:
        size, _, rest = line.partition("\t")
        ts, _, rel = rest.partition("\t")
        if not size.isdigit() or not rel or any(rel.startswith(s) or f"/{s}" in rel for s in SKIP):
            continue
        files.append({"name": rel, "size": int(size), "changed": int(float(ts or 0))})
    files.sort(key=lambda x: -x["changed"])
    return {"files": files[:LIST_MAX], "free": free}


def put(slug: str, folder: Path, name: str, data: bytes) -> str:
    """Загрузить файл в папку сессии; вернуть его имя (относительно папки)."""
    if len(data) > FILE_MAX:
        raise ValueError("файл больше 50 МБ")
    safe = file_name(name)
    stem, dot, ext = safe.rpartition(".")
    stem, ext = (stem, "." + ext) if dot and stem else (safe, "")
    q = shlex.quote
    out = sh(slug, f"cd {q(str(folder))} || exit 3; a=$(df -B1 --output=avail . | tail -1); "
                   f"[ \"$a\" -gt {len(data) + (1 << 20)} ] || {{ echo 'No space left'; exit 28; }}; "
                   f"n={q(safe)}; i=2; while [ -e \"$n\" ] || [ -L \"$n\" ]; do "
                   f"n={q(stem)}\" ($i)\"{q(ext)}; i=$((i+1)); done; "
                   ": > \"$n\" && printf '%s' \"$n\"")          # место занято сразу: второй загрузке — другое имя
    got = out.strip().splitlines()[-1] if out.strip() else ""
    if not got or "/" in got:
        raise RuntimeError("не вышло сохранить файл")
    if not data:                                          # пустой файл уже создан; буфер tmux пустым не бывает
        return got
    buf = "gp-up-" + secrets.token_hex(6)
    try:
        _tmux(slug, "load-buffer", "-b", buf, "-", data=data)
        _tmux(slug, "save-buffer", "-b", buf, str(folder / got))
    except RuntimeError:
        sh(slug, f"rm -f -- {q(str(folder / got))}")
        raise
    finally:
        subprocess.run([*tenants.tmux_of(slug).tmux, "delete-buffer", "-b", buf], capture_output=True)
    return got


def get(slug: str, folder: Path, rel: str) -> tuple[str, bytes]:
    """Скачать файл папки сессии: (имя, байты). Симлинк наружу, каталог, слишком большой — отказ."""
    rel = check_rel(rel)
    q = shlex.quote
    out = sh(slug, f"p=$(realpath -e -- {q(str(folder / rel))}) || {{ echo 'нет такого файла'; exit 4; }}; "
                   f"case \"$p\" in {q(str(folder))}/*) ;; "
                   "*) echo 'файл — только из папки этой сессии'; exit 5;; esac; "
                   "[ -f \"$p\" ] || { echo 'это не файл'; exit 6; }; stat -c %s -- \"$p\"; printf '%s' \"$p\"")
    lines = out.splitlines()
    if len(lines) < 2 or not lines[0].strip().isdigit():
        raise RuntimeError("не вышло прочитать файл")
    size, real = int(lines[0]), lines[1]
    if size > FILE_MAX:
        raise ValueError("файл больше 50 МБ — скачайте его по частям или попросите владельца")
    if size == 0:
        return rel.rsplit("/", 1)[-1], b""
    buf = "gp-dl-" + secrets.token_hex(6)
    try:
        _tmux(slug, "load-buffer", "-b", buf, real)
        data = _tmux(slug, "save-buffer", "-b", buf, "-")
    finally:
        subprocess.run([*tenants.tmux_of(slug).tmux, "delete-buffer", "-b", buf], capture_output=True)
    return rel.rsplit("/", 1)[-1], data
