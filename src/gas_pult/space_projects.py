"""«Проекты» в демо-пространстве (GAS-38 п.1, docs/PROJECTS.md 2.3, 2.5 п.5, 2.6): у клиента — тот же экран, что у
владельца. Проект пространства — папка ``home/projects/<имя>`` (та же, что у сессии задачи 32), чаты проекта — окна
пространства в этой папке и журналы Claude Code в ``config/claude/projects/<папка>``.

Id проекта — ``s:<пространство>:<папка>``. Тестировщику — только своё пространство: id чужого пространства, проекты
владельца, «..», «/», абсолютный путь — «проекта нет» (404). Владелец и админ открывают проекты любого пространства
(группа «Пространства»).

Пульт в пространство не пишет: папку создаёт ``space_sessions.create`` (команда от пользователя пространства), окно —
``tenants.new_window``. Список папок — ``space_sessions.listing`` (``home`` закрыт для пульта, 0700); журналы пульт
читает сам через группу ``pult-ro``. Журнал-ссылка (symlink) за пределы папки Claude пространства не читается:
агент клиента мог бы так показать в панели чужой файл.
"""

from __future__ import annotations

import base64
import contextlib
import os
import shlex
import time
from pathlib import Path

from gas_pult import projects, space_sessions, tenants, transcripts

PREFIX = "s:"
NOT_FOUND = "проекта нет — обновите список"
LIST_TTL = 20.0                                  # с: список папок — командой в пространстве, не чаще
INSTR_MAX = 4000                                 # инструкции нового проекта — одной командой tmux, коротко

_cache: dict[str, tuple[float, list[dict]]] = {}


def pid_of(slug: str, folder: str) -> str:
    return f"{PREFIX}{slug}:{folder}"


def is_space(pid) -> bool:
    return str(pid or "").startswith(PREFIX)


def parse(pid, allowed: str | None) -> tuple[str, str, Path]:
    """Id проекта → (пространство, папка, путь). ``allowed`` — пространство тестировщика (чужое — «проекта нет»);
    None — владелец (любое пространство). Папка — только прямо в ``home/projects`` (``space_sessions.check_folder``)."""
    s = str(pid or "")
    slug, sep, folder = s[len(PREFIX):].partition(":")
    if not s.startswith(PREFIX) or not sep:
        raise LookupError(NOT_FOUND)
    try:
        tenants.check_slug(slug)
        path = space_sessions.check_folder(slug, folder)
    except ValueError:
        raise LookupError(NOT_FOUND) from None
    if allowed is not None and slug != allowed:
        raise LookupError(NOT_FOUND)
    return slug, folder, path


def folder_of(slug: str, path: str) -> str:
    """Папка проекта, в которой (или глубже) окно: первая часть пути после ``home/projects``; иначе ""."""
    root = str(space_sessions.projects(slug))
    p = str(path or "")
    if not p.startswith(root + "/"):
        return ""
    name = p[len(root) + 1:].split("/", 1)[0]
    return name if name and name == space_sessions.folder_name(name) else ""


def listing(slug: str, fresh: bool = False) -> list[dict]:
    """Папки проектов [{folder, changed}] — из кэша на ``LIST_TTL`` секунд: команда в пространстве — не на каждый
    опрос панели."""
    c = _cache.get(slug)
    if fresh or not c or time.monotonic() - c[0] > LIST_TTL:
        rows = [{"folder": x["folder"], "changed": x["changed"]} for x in space_sessions.listing(slug)]
        c = _cache[slug] = (time.monotonic(), rows)
    return c[1]


def forget(slug: str):
    _cache.pop(slug, None)


def claude_home(slug: str) -> Path:
    return tenants.paths(slug)["claude"]


def own_file(slug: str, f: Path) -> bool:
    """Журнал лежит в папке Claude пространства, без ссылок наружу."""
    base = os.path.realpath(claude_home(slug)) + os.sep
    with contextlib.suppress(OSError):
        return not f.is_symlink() and os.path.realpath(f).startswith(base) and f.is_file()
    return False


def chat_files(slug: str, path: Path) -> list[Path]:
    """Журналы чатов проекта: ``config/claude/projects/<папка>/*.jsonl`` (не пакетные ``claude -p``)."""
    return [f for f in transcripts.transcripts(str(path), claude_home(slug))
            if own_file(slug, f) and not transcripts.is_batch(f)]


def chat_file(slug: str, path: Path, sid: str) -> Path:
    """Журнал чата по id — только среди журналов этой папки (id — uuid, путь не подставить)."""
    sid = transcripts.valid_sid(sid)
    f = next((f for f in chat_files(slug, path) if sid and f.stem == sid), None)
    if not f:
        raise LookupError("чата нет — Claude Code мог удалить старый журнал")
    return f


def open_sids(slug: str, path: Path, wins: list[dict]) -> tuple[dict, set]:
    """Окна проекта: id разговора → окно; у окна без метки занят последний журнал папки."""
    by_sid, legacy = {}, set()
    for w in wins:
        if w.get("space") != slug or folder_of(slug, w.get("path", "")) != path.name:
            continue
        if sid := transcripts.valid_sid(w.get("sid")):
            by_sid[sid] = w
        elif files := chat_files(slug, path):
            legacy.add(str(max(files, key=lambda x: x.stat().st_mtime)))
    return by_sid, legacy


def instructions(slug: str, path: Path) -> str:
    """``CLAUDE.md`` проекта — чтением от пользователя пространства (``home`` пульту закрыт)."""
    with contextlib.suppress(RuntimeError, OSError):
        return space_sessions.sh(slug, f"head -c 20000 -- {shlex.quote(str(path / 'CLAUDE.md'))} 2>/dev/null; true",
                                 timeout=10)
    return ""


def create(slug: str, name: str, text: str = "") -> Path:
    """«Новый проект»: папка ``home/projects/<имя>`` (занято — «имя 2»), инструкции — в ``CLAUDE.md`` той же командой
    от пользователя пространства (текст — base64: в команду попадают только буквы, цифры, «+», «/», «=»)."""
    text = str(text or "").strip()
    if len(text) > INSTR_MAX:
        raise ValueError(f"инструкции длиннее {INSTR_MAX} знаков — сократите")
    path = space_sessions.create(slug, name)
    if text:
        b64 = base64.b64encode((text + "\n").encode()).decode()
        space_sessions.sh(slug, f"printf %s {shlex.quote(b64)} | base64 -d > {shlex.quote(str(path / 'CLAUDE.md'))}")
    forget(slug)
    return path


def public(slug: str, folder: str, title: str) -> dict:
    """Поля проекта пространства — как у проекта владельца (``Panel.project_public``), без путей сервера."""
    return {"id": pid_of(slug, folder), "name": folder, "folder": folder, "path": "projects/" + folder, "paths": [],
            "origin": "space", "created": None, "profile": "", "model": "", "effort": "", "integrations": None,
            "repos": [], "pinned": False, "pinned_at": 0, "archived": False, "share": None,
            "space": slug, "space_title": title}


def stats(slug: str, path: Path) -> dict:
    return projects.stats(chat_files(slug, path))
