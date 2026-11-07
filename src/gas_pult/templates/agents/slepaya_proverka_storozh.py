"""Сторож слепого проверяющего: хук PreToolUse из определения агентов slepaya-proverka и slepaya-proverka-dokumentov.

По мотивам hooks/slepoy_guard.py из claude-pipeline (лицензия MIT; авторство — NOTICE.md репозитория gas-pult).

Слепой проверяющий видит только то, что ему передали в задании: требование и результат. Сторож держит эту границу:

- Чтение (Read, Grep, Glob) — только внутри путей, названных в задании полностью (от корня или от «~»), либо
  относительных путей, которые есть в рабочей папке. Остальное — отказ.
- Правила, память и история проекта закрыты всегда, даже внутри переданных путей: CLAUDE.md, MEMORY.md, AGENTS.md,
  журналы сессий, файлы входа и ключей.
- Read файла из папки со своим CLAUDE.md (кроме рабочей папки и выше) — отказ: Claude Code подложил бы агенту правила
  этой папки. Такой файл тот, кто ставит задачу, копирует в отдельную папку.
- Любой другой инструмент — отказ: проверяющий только читает.

Задание сторож берёт из журнала самого агента (``<сессия>/subagents/agent-<id>.jsonl``, первое сообщение). Журнала нет
или сторож упал — отказ (закрыто по умолчанию). Только стандартная библиотека Python.
"""

from __future__ import annotations

import json
import os
import re
import sys

NAMES = {"slepaya-proverka", "slepaya-proverka-dokumentov"}
READ_TOOLS = {"Read", "Grep", "Glob"}
FORBIDDEN = re.compile(
    r"(?i)(claude\.md|claude\.local\.md|memory\.md|agents\.md|[\\/]\.claude[\\/]projects([\\/]|$)|agent-memory"
    r"|\.credentials\.json|secrets\.json|[\\/]\.env(\.|$)|[\\/]\.ssh([\\/]|$)|[\\/]\.gnupg([\\/]|$)"
    r"|[\\/]\.password-store([\\/]|$)|\.kdbx$)"
)
QUOTED = re.compile(r"`([^`\n]+)`|«([^»\n]+)»|\"([^\"\n]+)\"")
BARE = re.compile(r"(?<![\w/.~-])((?:~|\.{1,2})?/[^\s`«»\"'<>|;,()\[\]{}]+"
                  r"|[\w.-]+(?:/[\w.-]+)+|[\w-]+\.[A-Za-z0-9]{1,5})")
TRAIL = ".,:;!?)»"
NOT_IN_TASK = ("Слепая проверка: этого пути нет в задании. Читать можно только то, что тебе передали (полные пути "
               "в задании). Нужен ещё файл — напиши в ответе, что не проверял, и чего не хватило.")


def deny(reason: str):
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason,
    }}, ensure_ascii=False))
    sys.exit(0)


def norm(path: str, cwd: str) -> str:
    path = os.path.expanduser(path)
    return os.path.realpath(path if os.path.isabs(path) else os.path.join(cwd, path))


def under(path: str, root: str) -> bool:
    root = root.rstrip(os.sep) or os.sep
    return path == root or path.startswith(root + os.sep) or root == os.sep


def agent_log(data: dict) -> str | None:
    """Журнал агента: сам ``transcript_path`` (если это журнал агента) или ``<сессия>/subagents/agent-<id>.jsonl``."""
    tp, aid = str(data.get("transcript_path") or ""), str(data.get("agent_id") or "")
    if not tp:
        return None
    if os.path.basename(tp).startswith("agent-"):
        return tp
    if aid:
        p = os.path.join(os.path.splitext(tp)[0], "subagents", f"agent-{aid}.jsonl")
        if os.path.isfile(p):
            return p
    return None


def task_text(log: str | None) -> str:
    """Первое сообщение агенту — его задание."""
    if not log:
        return ""
    try:
        with open(log, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                msg = rec.get("message") if isinstance(rec, dict) else None
                if rec.get("type") != "user" or not isinstance(msg, dict):
                    continue
                c = msg.get("content")
                if isinstance(c, str):
                    return c
                if isinstance(c, list):
                    return "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    except OSError:
        return ""
    return ""


def allowed_roots(task: str, cwd: str) -> list[str]:
    """Пути из задания: в кавычках или обратных кавычках (можно с пробелами) и без кавычек. Полный путь (от «/» или «~»)
    берётся всегда; относительный — если он есть в рабочей папке. Корень, домашняя папка и их предки — не берутся."""
    found = [next(g for g in m.groups() if g) for m in QUOTED.finditer(task)]
    found += [m.group(1) for m in BARE.finditer(task)]
    home = os.path.realpath(os.path.expanduser("~"))
    out = []
    for raw in found:
        raw = raw.strip().rstrip(TRAIL)
        if not raw or "\n" in raw:
            continue
        absolute = raw.startswith(("/", "~"))
        if not absolute and not os.path.exists(os.path.join(cwd, raw)):
            continue
        if not absolute and "/" not in raw and "." not in raw:
            continue
        p = norm(raw, cwd)
        if p == os.sep or under(home, p):                # «/», «/home», «~» — слишком широко: это не «передали»
            continue
        if p not in out:
            out.append(p)
    return out


def nested_claude_md(file_path: str, cwd: str) -> str | None:
    """CLAUDE.md в папке файла или выше — кроме рабочей папки и её предков (их правила агенту и так не даны)."""
    d = os.path.dirname(file_path)
    cwd = os.path.realpath(cwd)
    while True:
        if not under(cwd, d):
            for name in ("CLAUDE.md", "CLAUDE.local.md", os.path.join(".claude", "CLAUDE.md")):
                if os.path.isfile(os.path.join(d, name)):
                    return os.path.join(d, name)
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def targets(tool: str, inp: dict, cwd: str) -> list[str]:
    """Что инструмент откроет: Read — файл; Grep и Glob — папку поиска (нет — рабочая папка) и путь в шаблоне."""
    if tool == "Read":
        return [inp.get("file_path") or ""]
    base = inp.get("path") or cwd
    out = [base]
    pat = str(inp.get("pattern" if tool == "Glob" else "glob") or "")
    head = re.split(r"[*?{\[]", pat, maxsplit=1)[0]     # постоянная часть шаблона — до первого «*», «?», «{», «[»
    if pat.startswith(("/", "~")):
        out.append(head or "/")
    elif ".." in pat.split("/"):
        out.append(os.path.join(os.path.expanduser(str(base)), head or "."))
    return out


def check(data: dict) -> str | None:
    """Причина отказа или None — можно."""
    agent = str(data.get("agent_type") or "").split(":")[-1]
    if agent not in NAMES:
        return None                                      # сторож только для слепых проверяющих
    tool, inp = str(data.get("tool_name") or ""), data.get("tool_input") or {}
    cwd = str(data.get("cwd") or os.getcwd())
    if tool not in READ_TOOLS:
        return f"Слепая проверка: инструмент {tool} тебе не положен — ты только читаешь то, что передали."
    raw = [str(x) for x in targets(tool, inp, cwd)] + [str(inp.get("pattern") or ""), str(inp.get("glob") or "")]
    if any(FORBIDDEN.search(t) for t in raw if t):
        return ("Слепая проверка: правила, память и история проекта тебе не положены (CLAUDE.md, MEMORY.md, журналы "
                "сессий, ключи). Работай только по заданию.")
    roots = allowed_roots(task_text(agent_log(data)), cwd)
    if not roots:
        return ("Слепая проверка: в задании не нашёл ни одного пути к результату — читать нечего. Ответь «не принято: "
                "нечего проверять» и попроси передать полные пути.")
    for t in targets(tool, inp, cwd):
        p = norm(str(t), cwd)
        if not any(under(p, r) for r in roots):
            return NOT_IN_TASK
    if tool == "Read":
        found = nested_claude_md(norm(str(inp.get("file_path") or ""), cwd), cwd)
        if found:
            return ("Слепая проверка: файл лежит в папке со своими правилами — чтение подложило бы их тебе. Попроси "
                    "того, кто ставит задачу, скопировать файл в отдельную папку; в ответе — «не проверял».")
    return None


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
        reason = check(data if isinstance(data, dict) else {})
    except SystemExit:
        raise
    except Exception as e:                               # сторож не открывает дверь при сбое
        reason = f"Слепая проверка: сторож не смог проверить запрос ({type(e).__name__}) — чтение закрыто."
    if reason:
        deny(reason)


if __name__ == "__main__":
    main()
