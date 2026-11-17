"""Автопамять проекта — и в окна Pi, OpenCode, Hermes (владелец 17.11, приоритет №1: «Pi и OpenCode не видят
автопамять, то есть ваши решения из памяти»).

Claude Code сам читает память проекта: ``~/.claude/projects/<папка>/memory/MEMORY.md`` (оглавление) и файлы, на
которые она ссылается. Другие агенты этого не делают — пульт при запуске окна собирает ту же память в файл
``<настройки пульта>/agents/memory-<хэш папки>.md`` (0600) и отдаёт агенту его способом:

- Pi — вместе с добавкой правил в ``--append-system-prompt`` (один файл: правила + память);
- OpenCode — ``OPENCODE_CONFIG_CONTENT={"instructions": [файл]}`` (дополняет настройки, проверено
  ``opencode debug config``: свои MCP остаются);
- Hermes — переменная ``GAS_PULT_MEMORY_FILE``: обёртка ``hermes`` (штаб) дописывает файл к оверлею модели.

Память — это решения и привычки человека, а не секреты; всё равно файл — только владельцу (0600), размер ограничен
``LIMIT``. Только стандартная библиотека.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

LIMIT = 24_000                                         # знаков памяти в подсказку — не раздувать контекст
_LINK = re.compile(r"\]\(([^)\s]+\.md)\)")


def claude_key(path: str) -> str:
    """Имя папки проекта у Claude Code: путь, где каждый знак кроме букв и цифр — «-»."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def memory_dir(path: str, home: Path | None = None) -> Path:
    return (home or Path.home() / ".claude") / "projects" / claude_key(path) / "memory"


def collect(path: str, home: Path | None = None, limit: int = LIMIT) -> str:
    """Текст памяти проекта: оглавление ``MEMORY.md`` и файлы по его ссылкам (только из той же папки). Нет — ""."""
    d = memory_dir(path, home)
    try:
        index = (d / "MEMORY.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    parts = [index.strip()]
    base = d.resolve()
    for name in dict.fromkeys(_LINK.findall(index)):   # по порядку, без повторов
        f = (d / name).resolve()
        if f.parent != base or not f.is_file():          # только файлы самой папки памяти
            continue
        try:
            parts.append(f"### {name}\n\n" + f.read_text(encoding="utf-8").strip())
        except OSError:
            continue
    text = "\n\n".join(parts)
    return text if len(text) <= limit else text[:limit] + "\n\n…(память обрезана: больше лимита)"


def overlay(path: str, base: str = "", home: Path | None = None, out_dir: Path | None = None) -> Path | None:
    """Файл для агента: ``base`` (добавка правил Pi, может быть пустой) + память проекта. Памяти и base нет — None."""
    mem = collect(path, home)
    if not mem and not base:
        return None
    text = (base.strip() + "\n\n" if base.strip() else "") + (
        "## Память проекта (решения и привычки владельца — как у Claude Code)\n\n" + mem if mem else "")
    from gas_pult.config import config_dir, write_private
    d = out_dir or config_dir() / "agents"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    f = d / f"memory-{hashlib.sha1(str(path).encode()).hexdigest()[:10]}.md"
    write_private(f, text + "\n")
    return f
