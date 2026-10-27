"""Транскрипты Claude Code (``~/.claude/projects/<папка>/*.jsonl``): ответы, границы ходов, очистка для озвучки."""

from __future__ import annotations

import json
import re
from pathlib import Path

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def is_real_prompt(entry: dict) -> bool:
    """Настоящий запрос пользователя, а не tool_result, ! команда или служебная вставка."""
    c = entry.get("message", {}).get("content")
    if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
        return False
    t = text_of(c).strip()
    if not t or entry.get("isMeta"):
        return False
    return not re.match(r"<(bash-|local-command|command-|system-reminder|task-notification)", t)


def project_dir(path: str) -> Path:
    """Так Claude Code называет каталог транскриптов папки проекта."""
    return CLAUDE_PROJECTS / re.sub(r"[^A-Za-z0-9]", "-", path)


def transcripts(path: str) -> list[Path]:
    return sorted(project_dir(path).glob("*.jsonl"))


def clean(md: str) -> str:
    """Markdown → текст для синтеза речи: код и разделители таблиц не читаются, ссылки — подписью."""
    md = re.sub(r"```.*?```", " Блок кода пропущен. ", md, flags=re.S)
    md = re.sub(r"^\s*\|?[\s:|-]+\|[\s:|-]*$", "", md, flags=re.M)
    md = md.replace("|", ", ")
    md = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", md)
    md = re.sub(r"https?://\S+", " ссылка ", md)
    md = re.sub(r"[`*_#>]", "", md)
    md = re.sub(r"[ \t]+", " ", md)
    return re.sub(r"\n{2,}", "\n", md).strip()


class Turns:
    """Собирает текст ответа Claude из записей транскрипта и отдаёт его целиком на end_turn."""

    def __init__(self):
        self.buf: list[str] = []

    def feed(self, e: dict) -> str | None:
        if e.get("isSidechain"):            # субагенты — не ответ пользователю
            return None
        if e.get("type") == "user" and is_real_prompt(e):
            self.buf = []
        elif e.get("type") == "assistant":
            msg = e.get("message") or {}
            if t := text_of(msg.get("content")).strip():
                self.buf.append(t)
            if msg.get("stop_reason") == "end_turn":
                text, self.buf = "\n\n".join(self.buf), []
                return text if re.search(r"\w", text) else None   # «.» и пустые ходы — не шлём
        return None


class Tail:
    """Дочитывает новые целые строки jsonl; недописанную строку дочитает в следующий раз."""

    def __init__(self):
        self.offsets: dict[Path, int] = {}

    def track(self, f: Path, from_start: bool):
        self.offsets.setdefault(f, 0 if from_start else f.stat().st_size)

    def read(self, f: Path):
        with open(f, "rb") as fh:
            fh.seek(self.offsets[f])
            chunk = fh.read()
        cut = chunk.rfind(b"\n") + 1
        self.offsets[f] += cut
        for line in chunk[:cut].decode("utf-8", "replace").splitlines():
            try:
                yield json.loads(line)
            except ValueError:
                pass


def last_answer(path: str) -> str:
    """Последний полный ответ Claude в папке (для «💬 Последний ответ»)."""
    files = transcripts(path)
    if not files:
        return ""
    entries = []
    with open(max(files, key=lambda p: p.stat().st_mtime), encoding="utf-8") as fh:
        for line in fh:
            try:
                entries.append(json.loads(line))
            except ValueError:
                pass
    parts = []
    for e in reversed(entries):
        if e.get("isSidechain"):
            continue
        if e.get("type") == "assistant":
            if t := text_of(e.get("message", {}).get("content")).strip():
                parts.append(t)
        elif e.get("type") == "user" and is_real_prompt(e) and parts:
            break
    return "\n\n".join(reversed(parts))
