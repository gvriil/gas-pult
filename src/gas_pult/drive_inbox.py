"""Файлы владельца — сразу на Google Диск в папку проекта, не в inbox сервера (#217).

Решение владельца 15.11: «каждому проекту, которому создана папка на Google Диске, если я загружаю фото или данные
или ещё что-то — ты сразу не грузишь память [сервера], а сразу их загружаешь на Google Диск».

Диск смонтирован папкой (rclone mount): ``<корень Диска>/<проект>`` — папка проекта, имя = имя папки проекта
в корнях проектов (``project_roots``). Файл из панели или бота для сессии этого проекта ложится в
``<корень>/<проект>/Входящие/ГГГГ-ММ-ДД-<имя>`` (без перезаписи: ``-2``, ``-3``…). Нет монтирования, нет папки
проекта, ошибка записи — файл идёт в inbox пульта, как раньше, и строка в журнал (stderr). Файл не теряется.

Копирование — потоком, кусками (``CHUNK``): большой файл не читается в память целиком.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO

INBOX_DIR = "Входящие"                 # папка входящих в папке проекта на Диске
ARCHIVE_DIR = "Входящие-архив"         # старый inbox без известного проекта — сюда (в папку пульта)
ARCHIVE_PROJECT = "gas-pult"           # чья папка на Диске хранит архив
CHUNK = 1 << 20                        # 1 МБ за раз


def log(msg: str):
    print(f"drive-inbox: {msg}", file=sys.stderr, flush=True)


def drive_root(setting: str) -> Path | None:
    """Корень Диска: переменная ``GAS_PULT_DRIVE_ROOT`` (тесты), иначе настройка ``drive_root``; пусто — выключено."""
    raw = os.environ.get("GAS_PULT_DRIVE_ROOT", setting)
    return Path(os.path.expanduser(raw)) if raw else None


def project_of(path: str, roots: Iterable[Path]) -> str | None:
    """Имя проекта по пути окна: первая папка под одним из корней проектов (``~/projects/<имя>/…`` → ``<имя>``)."""
    if not path:
        return None
    p = Path(os.path.expanduser(path))
    for root in roots:
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        if rel.parts and not rel.parts[0].startswith("."):
            return rel.parts[0]
    return None


def project_dir(root: Path | None, project: str | None) -> Path | None:
    """Папка проекта на Диске, если Диск смонтирован и она есть; иначе None (тогда — inbox)."""
    if not root or not project or "/" in project or project in (".", ".."):
        return None
    d = root / project
    try:
        return d if d.is_dir() else None
    except OSError:                      # монтирование «отвалилось» — stat падает
        return None


def safe_name(name: str) -> str:
    """Имя файла без каталогов и опасных знаков: буквы (и кириллица) остаются, прочее → ``_``."""
    base = os.path.basename(name.replace("\\", "/"))
    return re.sub(r"[^\w.\-]+", "_", base)[-120:].lstrip(".") or "file"


def target(folder: Path, name: str, day: str) -> Path:
    """Свободное имя ``<day>-<name>`` в папке: занято — ``<day>-<stem>-2<ext>``, ``-3``…"""
    stem, ext = os.path.splitext(safe_name(name))
    n = 1
    while True:
        p = folder / f"{day}-{stem}{f'-{n}' if n > 1 else ''}{ext}"
        if not p.exists():
            return p
        n += 1


def _create(path: Path) -> BinaryIO:
    """Открыть новый файл только на запись (``x`` — чужой не перезаписать); занят (гонка) — ``-2``, ``-3``…"""
    stem, ext = os.path.splitext(path.name)
    n = 1
    while True:
        try:
            return open(path.with_name(f"{stem}{f'-{n}' if n > 1 else ''}{ext}"), "xb")
        except FileExistsError:
            n += 1


def copy_stream(src: BinaryIO, dst: BinaryIO, size: int | None = None) -> int:
    """Скопировать кусками; ``size`` — сколько байт прочитать (тело HTTP-запроса), None — до конца."""
    done = 0
    while size is None or done < size:
        chunk = src.read(CHUNK if size is None else min(CHUNK, size - done))
        if not chunk:
            break
        dst.write(chunk)
        done += len(chunk)
    if size is not None and done != size:
        raise OSError(f"получено {done} из {size} байт")
    return done


def save(src: BinaryIO, name: str, *, folder: Path | None, inbox: Path, inbox_name: str,
         size: int | None = None, day: str | None = None) -> Path:
    """Сохранить поток: в ``folder/Входящие`` (папка проекта на Диске), не вышло — в ``inbox/inbox_name``.

    Ошибка до чтения потока (нет Диска, нельзя создать папку или файл) — сразу inbox. Ошибка посреди записи
    (поток — тело HTTP, назад не перемотать): в inbox — уже записанное на Диск, недописанный кусок и остаток
    потока; начало с Диска не читается — ошибка наверх (клиент увидит «не загрузился» и повторит)."""
    day = day or time.strftime("%Y-%m-%d")
    if folder is None:
        return _to_inbox(src, inbox, inbox_name, size)
    try:
        box = folder / INBOX_DIR
        box.mkdir(exist_ok=True)
        f = _create(target(box, name, day))
    except OSError as e:
        log(f"нет записи на Диск ({folder.name}): {e} — кладу в inbox")
        return _to_inbox(src, inbox, inbox_name, size)
    dst, done, chunk = Path(f.name), 0, b""
    try:
        with f:
            while size is None or done < size:
                chunk = src.read(CHUNK if size is None else min(CHUNK, size - done))
                if not chunk:
                    break
                f.write(chunk)
                done, chunk = done + len(chunk), b""
        if size is not None and done != size:
            raise EOFError(f"получено {done} из {size} байт")      # клиент оборвал — не наша ошибка записи
        with contextlib.suppress(OSError):        # rclone mount может не поддерживать права — не ошибка
            os.chmod(dst, 0o600)
        return dst
    except EOFError:
        _drop(dst)
        raise OSError(f"файл пришёл не целиком: {done} из {size} байт") from None
    except OSError as e:
        log(f"обрыв записи на Диск ({folder.name}, {done} Б): {e} — кладу в inbox")
        path = inbox / inbox_name
        inbox.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(path, "wb") as out:
            with open(dst, "rb") as head:
                copy_stream(head, out, done)             # начало не читается — OSError наверх
            out.write(chunk)
            copy_stream(src, out, None if size is None else size - done - len(chunk))
        path.chmod(0o600)
        _drop(dst)
        return path


def _drop(path: Path):
    try:
        path.unlink()
    except OSError:
        pass


def _to_inbox(src: BinaryIO, inbox: Path, inbox_name: str, size: int | None) -> Path:
    inbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = inbox / inbox_name
    with open(path, "wb") as f:
        copy_stream(src, f, size)
    path.chmod(0o600)
    return path


def move(src: Path, folder: Path, name: str, day: str) -> Path:
    """Перенести файл в ``folder/Входящие`` (или в другую папку на Диске): копия потоком → размер на Диске совпал →
    только тогда удалить локальный. Не совпал — копию с Диска убрать, локальный оставить, ``OSError``."""
    folder.mkdir(parents=True, exist_ok=True)
    want = src.stat().st_size
    dst = target(folder, name, day)
    with open(src, "rb") as r, _create(dst) as w:
        dst = Path(w.name)
        copy_stream(r, w)
    got = dst.stat().st_size
    if got != want:
        _drop(dst)
        raise OSError(f"размер на Диске {got} ≠ {want}: {src.name} оставлен в inbox")
    src.unlink()
    return dst


def place(local: Path, *, folder: Path | None, day: str | None = None) -> Path:
    """Файл, уже скачанный в inbox (вложение бота), — в папку проекта на Диске; нельзя — остаётся в inbox."""
    if folder is None:
        return local
    try:
        return move(local, folder / INBOX_DIR, strip_stamp(local.name), day or time.strftime("%Y-%m-%d"))
    except OSError as e:
        log(f"не перенёс на Диск ({folder.name}): {e} — файл в inbox")
        return local


# ---------- перенос старого inbox: gas-pult inbox migrate ----------

STAMP = re.compile(r"^(?P<d>\d{8})-\d{6}-(?:[0-9a-f]{6}-)?(?P<rest>.+)$")


def strip_stamp(name: str) -> str:
    """``20261115-101500-ab12cd-фото.jpg`` / ``20261115-101500-фото.jpg`` → ``фото.jpg``."""
    m = STAMP.match(name)
    return m.group("rest") if m else name


def day_of(path: Path) -> str:
    m = STAMP.match(path.name)
    if m:
        d = m.group("d")
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime))


def skip(path: Path) -> bool:
    """Не переносить: отчёты «#ревью» и их вложения (их разбирает таймер штаба в inbox), скрытые файлы."""
    return path.name.startswith(".") or "ревью" in path.name or path.name.startswith("review")


def transcript_projects(claude_dir: Path, names: set[str], roots: list[Path]) -> dict[str, str]:
    """Имя файла inbox → проект: в журналах Claude Code (``*.jsonl``) путь к файлу встречается в сообщении, а в
    той же записи — ``cwd`` сессии. Читаем построчно, разбираем только строки с ``inbox/``."""
    found: dict[str, str] = {}
    if not names or not claude_dir.is_dir():
        return found
    for jl in claude_dir.glob("*/*.jsonl"):
        try:
            with open(jl, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if "inbox/" not in line:
                        continue
                    hits = [n for n in names if n not in found and f"inbox/{n}" in line]
                    if not hits:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    cwd = rec.get("cwd") if isinstance(rec, dict) else ""
                    if proj := project_of(str(cwd or ""), roots):
                        for n in hits:
                            found[n] = proj
        except OSError:
            continue
    return found


def migrate(inbox: Path, root: Path, roots: list[Path], *, claude_dir: Path | None = None, dry_run: bool = False,
            archive_project: str = ARCHIVE_PROJECT) -> list[dict]:
    """Старый inbox → Диск. Проект известен (по журналам Claude Code) и папка его есть — ``<проект>/Входящие``,
    иначе ``<archive_project>/Входящие-архив``. Локальная копия удаляется только после сверки размера.
    Возвращает строки отчёта: ``{"file", "to", "ok", "error"}``."""
    if not root.is_dir():
        raise OSError(f"нет корня Диска {root} — Диск не смонтирован?")
    files = sorted(p for p in inbox.iterdir() if p.is_file() and not skip(p)) if inbox.is_dir() else []
    projects = transcript_projects(claude_dir, {p.name for p in files}, roots) if claude_dir else {}
    out = []
    for p in files:
        proj = projects.get(p.name)
        folder = project_dir(root, proj)
        dest = folder / INBOX_DIR if folder else root / archive_project / ARCHIVE_DIR
        row = {"file": p.name, "to": str(dest), "size": p.stat().st_size, "ok": False, "error": ""}
        if dry_run:
            row["ok"] = True
        else:
            try:
                row["to"] = str(move(p, dest, strip_stamp(p.name), day_of(p)))
                row["ok"] = True
            except OSError as e:
                row["error"] = str(e)
        out.append(row)
    return out
