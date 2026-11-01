"""Транскрипты Claude Code (``~/.claude/projects/<папка>/*.jsonl``): ответы, границы ходов, очистка для озвучки."""

from __future__ import annotations

import json
import re
from pathlib import Path

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2190-\u21FF\u2300-\u23FF\u25A0-\u25FF"
                   "\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]")


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
    md = re.sub(r"[`*_#>\\]", "", md)
    md = EMOJI.sub("", md)                      # эмодзи и стрелки синтез читает словами («треугольник вправо»)
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
    """Дочитывает новые целые строки jsonl; недописанную строку дочитает в следующий раз.

    Старое не пересылаем. Файлы, которые уже лежали в папке, когда её увидели впервые, читаем с конца; с начала —
    только файл, появившийся позже (новая сессия), или маленький свежий — сессия, открытая вместе с окном. Время
    изменения (ctime) старого журнала ничего не значит: его меняет любая запись или chmod — по нему 31.10 бот принял
    журналы на 11–18 МБ за новые и переслал всю переписку (>170 сообщений, 429). Файл подменили или укоротили —
    тоже с конца."""

    FRESH = 64 * 1024                                       # «свежая сессия» при первом взгляде на папку — до 64 КБ

    def __init__(self, started: float = 0.0):
        self.offsets: dict[Path, int] = {}
        self.inodes: dict[Path, int] = {}
        self.folders: set[str] = set()
        self.started = started

    def track(self, f: Path, from_start: bool):
        if f not in self.offsets:
            st = f.stat()
            self.offsets[f], self.inodes[f] = (0 if from_start else st.st_size), st.st_ino

    def watch(self, folder: str, files: list[Path]):
        """Файлы папки: первый взгляд на папку — всё с конца (кроме маленьких свежих), потом новые — с начала."""
        first = folder not in self.folders
        self.folders.add(folder)
        for f in files:
            if f not in self.offsets:
                st = f.stat()
                self.track(f, not first or (st.st_size < self.FRESH and st.st_mtime > self.started))

    def read(self, f: Path):
        st = f.stat()
        if st.st_ino != self.inodes.get(f, st.st_ino) or st.st_size < self.offsets[f]:   # подменили / укоротили
            self.offsets[f], self.inodes[f] = st.st_size, st.st_ino
            return
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


PASTED = re.compile(r"</?pasted_content[^>]*>")


def revision(path: str) -> str:
    """Отпечаток последнего транскрипта папки (файл, размер, время) — изменился ли журнал с прошлого раза."""
    files = transcripts(path)
    if not files:
        return ""
    f = max(files, key=lambda p: p.stat().st_mtime)
    st = f.stat()
    return f"{f.stem[:8]}-{st.st_size}-{st.st_mtime_ns}"


def history(path: str, limit: int = 30, before: int | None = None) -> tuple[list[dict], bool]:
    """Переписка сессии из последнего транскрипта папки: [{i, role, text, ts, queued?}], есть ли раньше.

    Ответ Claude — весь текст хода до следующего запроса человека (как в чате), субагенты пропускаются.
    Сообщение, отправленное, пока Claude занят, Claude Code ставит в очередь (``queue-operation``) и отдаёт
    по ходу работы (``attachment: queued_command``): такие показываем сразу, с пометкой
    ``queued`` = "wait" (ещё в очереди) или "read" (прочитано по ходу работы).
    """
    files = transcripts(path)
    if not files:
        return [], False
    items: list[dict] = []
    with open(max(files, key=lambda p: p.stat().st_mtime), encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("isSidechain"):
                continue
            ts = e.get("timestamp", "")[:16].replace("T", " ")
            kind = e.get("type")
            if kind == "queue-operation" and e.get("operation") == "enqueue" and str(e.get("content", "")).strip():
                items.append({"role": "user", "text": PASTED.sub("", e["content"]).strip(), "ts": ts, "queued": "wait"})
            elif kind == "attachment" and (e.get("attachment") or {}).get("type") == "queued_command":
                text = PASTED.sub("", str(e["attachment"].get("prompt", ""))).strip()
                q = next((x for x in reversed(items) if x.get("queued") == "wait" and x["text"] == text), None)
                if q:
                    q["queued"] = "read"
                elif text:
                    items.append({"role": "user", "text": text, "ts": ts, "queued": "read"})
            elif kind == "user" and is_real_prompt(e):
                text = PASTED.sub("", text_of(e["message"]["content"])).strip()
                # очередь, которую Claude взял обычным ходом, — не дублируем
                items = [x for x in items if not (x.get("queued") == "wait" and x["text"] == text)]
                items.append({"role": "user", "text": text, "ts": ts})
            elif e.get("type") == "assistant" and (t := text_of((e.get("message") or {}).get("content")).strip()):
                if items and items[-1]["role"] == "assistant":
                    items[-1]["text"] += "\n\n" + t
                else:
                    items.append({"role": "assistant", "text": t, "ts": ts})
    for i, it in enumerate(items):
        it["i"] = i
    end = len(items) if before is None else max(0, min(before, len(items)))
    start = max(0, end - limit)
    return items[start:end], start > 0


TOOLS = {"Bash": "команда", "Read": "читает", "Edit": "правит", "MultiEdit": "правит", "Write": "пишет",
         "Grep": "ищет", "Glob": "ищет файлы", "WebFetch": "открывает", "WebSearch": "ищет в сети",
         "Task": "поручил агенту", "Agent": "поручил агенту", "TodoWrite": "план"}


def preview(path: str, tail: int = 262144) -> str:
    """Одна строка о том, что сейчас в сессии: последний ответ Claude, его действие или ваш запрос.

    Читается только хвост журнала (``tail`` байт) — дёшево даже при опросе раз в 3 секунды.
    """
    files = transcripts(path)
    if not files:
        return ""
    with open(max(files, key=lambda p: p.stat().st_mtime), "rb") as fh:
        start = max(0, fh.seek(0, 2) - tail)
        fh.seek(start)
        lines = fh.read().decode("utf-8", "replace").splitlines()[1 if start else 0:]   # первая строка хвоста — обрывок
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("isSidechain"):
            continue
        content, found = (e.get("message") or {}).get("content"), ""
        if e.get("type") == "assistant":
            found = _line(text_of(content))
            use = next((b for b in content or [] if isinstance(b, dict) and b.get("type") == "tool_use"), None)
            if not found and use:
                arg = use.get("input") or {}
                what = (arg.get("description") or arg.get("command") or arg.get("file_path") or arg.get("pattern")
                        or arg.get("url") or arg.get("query") or "")
                verb = TOOLS.get(use.get("name", ""), use.get("name", "").split("__")[-1])
                found = _line(f"{verb[:1].upper()}{verb[1:]}: {what}" if what else verb)
        elif e.get("type") == "user" and is_real_prompt(e) and not text_of(content).startswith("[Request interrupted"):
            found = _line("Вы: " + PASTED.sub("", text_of(content)))
        if found:
            return found
    return ""


def last_model(path: str, tail: int = 262144) -> str:
    """На какой модели ответил Claude в последний раз — поле ``message.model`` в журнале (хвост ``tail`` байт).

    Запасной источник, когда в строке статуса Claude Code нет «🤖 …»: id как есть (claude-opus-5-5, glm-5.3…),
    подпись для людей — ``model_title``.
    """
    files = transcripts(path)
    if not files:
        return ""
    with open(max(files, key=lambda p: p.stat().st_mtime), "rb") as fh:
        start = max(0, fh.seek(0, 2) - tail)
        fh.seek(start)
        lines = fh.read().decode("utf-8", "replace").splitlines()[1 if start else 0:]
    for line in reversed(lines):
        if '"model"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        m = (e.get("message") or {}).get("model") if e.get("type") == "assistant" and not e.get("isSidechain") else ""
        if m and not m.startswith("<"):              # «<synthetic>» — служебные ответы Claude Code, не модель
            return m
    return ""


def model_title(model_id: str) -> str:
    """claude-opus-5-5 → «Opus 5.5», claude-sonnet-4-5-20250929 → «Sonnet 4.5»; чужие id — как есть."""
    m = re.match(r"claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?$", model_id)
    if not m:
        return model_id
    return f"{m.group(1).capitalize()} {m.group(2)}" + (f".{m.group(3)}" if m.group(3) else "")


def _line(text: str, limit: int = 140) -> str:
    """Первая содержательная строка без разметки Markdown и эмодзи."""
    for raw in text.splitlines():
        t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw)                 # ссылка → подпись
        t = re.sub(r"^\s*(#+|>|[-+*](?=\s))\s*", "", t)               # заголовок, цитата, пункт списка
        t = EMOJI.sub("", re.sub(r"[`*]", "", t).replace("|", " "))     # «#» и «_» в адресах не трогаем
        t = re.sub(r"\s+", " ", t).strip(" :-")
        if re.search(r"\w", t):                        # строки из одних знаков («·», «---») пропускаем
            return t[:limit]
    return ""


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
