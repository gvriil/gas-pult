"""Папки, которые человек создал или выбрал через пульт, — доверенные для Claude Code заранее (владелец 25.11:
«диалог “доверять папке?” не должен появляться вообще»).

Claude Code хранит согласие в своём файле настроек (``<CLAUDE_CONFIG_DIR>/.claude.json`` или ``~/.claude.json``):
``projects[<папка>].hasTrustDialogAccepted``. Пульт ставит этот флаг до запуска окна — тогда вопроса нет, и не нужно
отвечать на него нажатиями (их Claude Code может не принять, пока не готов; узкое окно переносит пункты).

Границы:
- только папки ВНУТРИ корней проектов (``project_roots``): не сам корень, не домашняя папка, не ``/`` — согласие на
  родительскую папку Claude Code распространяет на все вложенные (проверено 25.11 на 2.1.332);
- файл настроек не создаём: его нет — Claude ещё не запускали, ответит автоответ (``tmux.accept_trust``);
- запись атомарная (временный файл рядом и ``os.replace``) под своим замком, права файла сохраняются; другие ключи не
  трогаем. Любая ошибка — ``False``, окно всё равно откроется, а вопрос закроет автоответ.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path


def config_file(home: str | Path | None = None) -> Path:
    """Файл настроек Claude Code: папка ``home`` (своя папка Claude участника) → ``$CLAUDE_CONFIG_DIR`` → ``~``."""
    base = home or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~")
    return Path(base) / ".claude.json"


def inside(path: str | Path, roots: list[Path]) -> bool:
    """Папка строго внутри одного из корней проектов (сам корень — нет: согласие на него — на всё внутри)."""
    p = Path(os.path.abspath(os.path.expanduser(str(path))))
    for r in roots:
        r = Path(os.path.abspath(os.path.expanduser(str(r))))
        if p != r and r in p.parents:
            return True
    return False


def trusted(path: str | Path, home: str | Path | None = None) -> bool:
    try:
        d = json.loads(config_file(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    key = os.path.abspath(os.path.expanduser(str(path)))
    return bool(((d.get("projects") or {}).get(key) or {}).get("hasTrustDialogAccepted"))


def ensure(path: str | Path, roots: list[Path], home: str | Path | None = None) -> bool:
    """Отметить папку доверенной до запуска Claude Code. True — флаг стоит (уже был или поставили)."""
    if not inside(path, roots):
        return False
    key = os.path.abspath(os.path.expanduser(str(path)))
    f = config_file(home)
    if not f.is_file():
        return False
    if trusted(key, home):
        return True
    try:
        from gas_pult.config import data_dir  # замок — у пульта, не мусорим в домашней папке
        with open(data_dir() / "claude-trust.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            d = json.loads(f.read_text(encoding="utf-8"))        # перечитать под замком: файл пишет и Claude Code
            if not isinstance(d, dict):
                return False
            projects = d.setdefault("projects", {})
            entry = projects.setdefault(key, {})
            if entry.get("hasTrustDialogAccepted") is True:
                return True
            entry["hasTrustDialogAccepted"] = True
            mode = f.stat().st_mode & 0o777
            fd, tmp = tempfile.mkstemp(prefix=".claude.json.", dir=str(f.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as out:
                    json.dump(d, out, ensure_ascii=False, indent=2)
                    out.flush()
                    os.fsync(out.fileno())
                os.chmod(tmp, mode)
                os.replace(tmp, f)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        return trusted(key, home)
    except (OSError, ValueError):
        return False
