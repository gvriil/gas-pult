"""Журнал доставок в окна: ``<данные>/sends.jsonl`` (0600) — без самого текста.

Каждая строка — одно событие: отправка из панели, бота, фокус-ссылки, расписания или живого терминала, повторный
Enter после перепроверки, «не отправлено — висит в поле ввода». Пишем время, окно, источник, длину и отпечатки текста
(sha256 — первые 12 знаков; ``head`` — отпечаток первых 40 знаков без пробелов: по нему сторож узнаёт свой текст в поле
ввода, где он виден с переносами или обрезанным), итог вставки и что осталось в поле ввода. По журналу видно, откуда
пришёл текст, который потом висел неотправленным (10.11 разобрать было нечем).

Бот и панель — разные процессы и пишут в один файл: запись под ``flock``. Больше ``KEEP`` строк — старые срезаются.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

KEEP = 5000                 # строк в журнале; при KEEP + SLACK срезаем до KEEP
SLACK = 500
HEAD = 40                   # столько знаков (без пробелов) сравнивает tmux.is_ours


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:12]


def head(text: str) -> str:
    """Отпечаток начала текста без пробелов и переносов (как сравнивает ``tmux.is_ours``)."""
    return sha(_norm(text)[:HEAD])


def matches(draft: str, rec: dict) -> bool:
    """Черновик в поле ввода — это текст из записи журнала? Сравниваем отпечатки начала: у короткого черновика —
    весь, у длинного — первые 40 знаков. Свёрнутую вставку («[Pasted text #1 …]») по отпечатку не узнать — не наша."""
    d = _norm(draft)
    if not d or not rec.get("head"):
        return False
    return sha(d[:HEAD]) == rec["head"]


class Log:
    def __init__(self, path: Path, keep: int = KEEP, clock=time.time):
        self.path, self.keep, self.clock = Path(path), keep, clock
        self.lock = threading.Lock()

    def record(self, wid: str, src: str, text: str | None = None, **extra) -> dict:
        """Одно событие. ``text`` — только для длины и отпечатков, в файл не попадает."""
        rec = {"ts": round(self.clock(), 3), "w": wid, "src": src}
        if text is not None:
            rec |= {"len": len(text), "sha": sha(text), "head": head(text)}
        rec |= {k: v for k, v in extra.items() if v is not None}
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self.lock:
                fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, "r+") as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    os.fchmod(f.fileno(), 0o600)
                    f.write(line)
                    f.flush()
                    f.seek(0)
                    lines = f.readlines()
                    if len(lines) > self.keep + SLACK:      # ротация: оставить последние KEEP строк
                        f.seek(0)
                        f.truncate()
                        f.writelines(lines[-self.keep:])
        except OSError as e:                                 # журнал не должен ломать доставку
            print("sends.jsonl:", e, flush=True)
        return rec

    def recent(self, within: float = 3600) -> list[dict]:
        since = self.clock() - within
        out = []
        try:
            with open(self.path) as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if r.get("ts", 0) >= since:
                        out.append(r)
        except OSError:
            return []
        return out

    def match(self, wid: str, draft: str, within: float = 3600) -> dict | None:
        """Последняя доставка пульта в это окно за ``within`` с, чей текст сейчас в поле ввода (``draft``)."""
        for r in reversed(self.recent(within)):
            if r.get("w") == wid and r.get("res") and r.get("head") and matches(draft, r):
                return r
        return None

    def last_unsent(self, wid: str, within: float = 3600) -> dict | None:
        return next((r for r in reversed(self.recent(within)) if r.get("w") == wid and r.get("res") == "unsent"), None)

    def notified(self, wid: str, sha12: str, within: float = 3600) -> bool:
        """Владельцу уже сказали «не отправлено» об этом тексте в этом окне — второй раз не говорим."""
        return any(r.get("w") == wid and r.get("sha") == sha12 and r.get("res") == "unsent"
                   for r in self.recent(within))
