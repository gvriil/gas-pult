"""«#ревью» в боте: отчёт внешнего ревью (ChatGPT и др.) — не в сессию, а файлом в inbox для разбора.

Владелец пишет или пересылает боту сообщение, начинающееся с «#ревью» (регистр не важен, после метки — пробелы,
перевод строки или двоеточие). Бот сохраняет текст в ``<данные пульта>/inbox/ревью-ГГГГ-ММ-ДД-ЧЧММ.md``
(папка 0700, файл 0600; совпала минута — суффикс ``-2``, ``-3``…) и отвечает «принято, разберу в 14:00» /
«в 21:00» / «завтра в 14:00» — когда ближайший запуск разбора (таймер штаба читает ``inbox/*ревью*``).

Длинный отчёт приходит несколькими сообщениями — склейка (``Collector``): после сообщения с меткой в течение
``GLUE`` секунд от предыдущей части в тот же файл дописываются сообщения того же владельца в том же чате, если:
  • сообщение переслано (пересылка с комментарием «#ревью»: Telegram шлёт комментарий первым, пересылки — следом);
  • или предыдущая часть длинная (≥ ``SPLIT`` символов) — Telegram сам разрезал вставленный текст на куски;
  • или сообщение с меткой было пустым («#ревью» и больше ничего) — ждём сам отчёт следующим сообщением.
Команды («/…») и кнопки меню цепочку обрывают и работают как обычно. Части идут в файл по порядку message_id.

Содержимое отчёта в журнал службы не пишется. Telegram ID в файл не попадают — только имя и @username источника.
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

LABEL = re.compile(r"^\s*#ревью(?![\w])[\s:.\-—–]*", re.I)
GLUE = 30.0                     # секунд от предыдущей части: следующая ещё та же «посылка»
SPLIT = 3500                    # часть такой длины — скорее всего, кусок, отрезанный Telegram (лимит 4096)
SLOTS = (14, 21)                # когда таймер штаба разбирает inbox (местное время сервера)
ATT_DIR = "review-att"          # вложения — отдельно: имя не должно попасть под маску *ревью*


def labeled(text: str) -> str | None:
    """Текст после метки «#ревью» или ``None``, если метки в начале нет."""
    mt = LABEL.match(text or "")
    return text[mt.end():].strip() if mt else None


def when(now: datetime) -> str:
    """Ближайший запуск разбора: «в 14:00», «в 21:00» или «завтра в 14:00»."""
    for h in SLOTS:
        if (now.hour, now.minute) < (h, 0):
            return f"в {h}:00"
    return f"завтра в {SLOTS[0]}:00"


def reply(now: datetime) -> str:
    return f"принято, разберу {when(now)}"


def origin(m: dict) -> str:
    """От кого переслано: имя и @username (без Telegram ID); «» — не пересылка."""
    o = m.get("forward_origin")
    if o:
        kind = o.get("type")
        if kind == "user":
            u = o.get("sender_user") or {}
            name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x)
            return name + (f" (@{u['username']})" if u.get("username") else "") or "пользователь"
        if kind == "hidden_user":
            return o.get("sender_user_name") or "скрытый пользователь"
        c = o.get("chat") or o.get("sender_chat") or {}
        title = c.get("title") or "чат"
        return title + (f" (@{c['username']})" if c.get("username") else "")
    if m.get("forward_sender_name"):                       # старые поля Bot API
        return m["forward_sender_name"]
    if u := m.get("forward_from"):
        return u.get("first_name") or "пользователь"
    if c := m.get("forward_from_chat"):
        return c.get("title") or "чат"
    return ""


def forwarded(m: dict) -> bool:
    return bool(m.get("forward_origin") or m.get("forward_from") or m.get("forward_from_chat")
                or m.get("forward_sender_name"))


def render(parts: list[dict], started: datetime) -> str:
    """Файл для разбора: заголовок, метаданные, исходный текст целиком."""
    parts = sorted(parts, key=lambda p: p["id"])
    tz = started.astimezone().strftime("%z")
    srcs = list(dict.fromkeys(p["from"] for p in parts if p["from"]))
    files = [p["file"] for p in parts if p.get("file")]
    head = [f"# Ревью {started:%Y-%m-%d %H:%M}", "",
            f"- Дата: {started:%Y-%m-%d %H:%M} (UTC{tz[:3]}:{tz[3:]})",
            "- Источник: Telegram, бот пульта — сообщение владельца с меткой #ревью"
            + (" (пересланное)" if srcs else ""),
            f"- Переслано от: {', '.join(srcs) if srcs else '—'}",
            f"- Частей: {len(parts)}"]
    if files:
        head.append("- Вложения: " + ", ".join(files))
    body = "\n\n".join(p["text"] for p in parts if p["text"]) or "(текст не пришёл — см. вложения)"
    return "\n".join(head) + "\n\n---\n\n" + body + "\n"


def reserve(inbox: Path, now: datetime) -> Path:
    """Новый пустой файл 0600 с уникальным именем; папка — 0700."""
    inbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(inbox, 0o700)
    base = f"ревью-{now:%Y-%m-%d-%H%M}"
    for n in range(1, 1000):
        path = inbox / (base + (f"-{n}" if n > 1 else "") + ".md")
        try:
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            return path
        except FileExistsError:
            continue
    raise OSError("нет свободного имени файла ревью")


def write(path: Path, text: str):
    """Перезапись целиком через временный файл (0600) — разбор не увидит половину."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".review-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class Collector:
    """Открытые «посылки» ревью по чатам: склейка частей и запись файла."""

    def __init__(self, inbox: Path, clock=time.time, now=datetime.now):
        self.inbox, self.clock, self.now = inbox, clock, now
        self.open: dict[int, dict] = {}                    # чат → {path, parts, at, started, empty_head}
        self.lock = threading.Lock()

    def start(self, chat: int, m: dict, text: str, file: str = "") -> Path:
        started = self.now()
        with self.lock:
            path = reserve(self.inbox, started)
            box = {"path": path, "parts": [], "at": self.clock(), "started": started, "wait": not text and not file}
            self.open[chat] = box
            self._add(box, m, text, file)
        return path

    def wants(self, chat: int, m: dict, text: str) -> bool:
        """Продолжение ли это открытой посылки (правила — в описании модуля)."""
        with self.lock:
            box = self.open.get(chat)
            if not box or self.clock() - box["at"] > GLUE:
                self.open.pop(chat, None)
                return False
            if text.startswith("/") or m.get("voice") or m.get("audio") or m.get("contact"):
                self.open.pop(chat, None)
                return False
            last = max(box["parts"], key=lambda p: p["id"])
            return forwarded(m) or box["wait"] or len(last["text"]) >= SPLIT

    def add(self, chat: int, m: dict, text: str, file: str = "") -> Path:
        with self.lock:
            box = self.open[chat]
            box["wait"] = False
            self._add(box, m, text, file)
            return box["path"]

    def _add(self, box: dict, m: dict, text: str, file: str):
        box["parts"].append({"id": m.get("message_id", 0), "text": text, "from": origin(m), "file": file})
        box["at"] = self.clock()
        write(box["path"], render(box["parts"], box["started"]))
