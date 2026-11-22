"""Журнал событий чата для отладки (GAS-31, урезанно; владелец 19.11: «надеюсь, на бэке идёт логирование всех
процессов чата, чтобы заниматься отладкой»): ``<данные>/chat-events.jsonl`` (0600), одна строка — одно событие.

Путь одного сообщения — по его id (``mid`` — id сообщения панели, у бота — ``tg:<id>``):
``recv`` (принято сервером: окно, источник, устройство и вход) → ``inserted`` / ``unsent`` / ``dup`` (вставка в окно)
→ ``repeat_stop`` (тот же вопрос недавно, #286) → ``answer_tg`` (ответ ушёл в Telegram / ``answer_tg_fail`` с кодом).
Голос: ``stt_start`` → ``stt_done`` / ``stt_fail`` (по id задания). Браузер: ``js_error`` (тип, экран, место).

Текста сообщений нет: только длина и отпечаток ``sha`` (тот же, что в ``sends.jsonl`` — по нему связка с журналом
доставок). Хранится ``KEEP_DAYS`` дней: раз в сутки старые строки срезаются. Бот и панель пишут в один файл под
``flock``. Журнал никогда не ломает доставку: ошибка записи — строка в stderr.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

KEEP_DAYS = 30
FIELD_MAX = 200                     # строковые поля обрезаются: в журнал не попадёт длинный текст


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:12]


class Log:
    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock, self.lock = Path(path), clock, threading.Lock()
        self.pruned = 0.0

    def event(self, ev: str, mid: str = "", **kw) -> dict:
        rec = {"ts": round(self.clock(), 3), "ev": ev}
        if mid:
            rec["mid"] = str(mid)[:80]
        for k, v in kw.items():
            if v is None or v == "":
                continue
            rec[k] = v[:FIELD_MAX] if isinstance(v, str) else v
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self.lock:
                fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, "r+") as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    f.write(line)
                    f.flush()
                    if rec["ts"] - self.pruned > 86400:      # раз в сутки — срезать старше KEEP_DAYS
                        self.pruned = rec["ts"]
                        f.seek(0)
                        keep = [x for x in f.readlines() if _ts(x) >= rec["ts"] - KEEP_DAYS * 86400]
                        f.seek(0)
                        f.truncate()
                        f.writelines(keep)
        except OSError as e:
            print(f"chat-events.jsonl: {e}", file=sys.stderr, flush=True)
        return rec

    def trail(self, mid: str) -> list[dict]:
        """Все события одного сообщения или задания (для экрана отладки и поиска «где застряло»)."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for x in lines:
            try:
                r = json.loads(x)
            except ValueError:
                continue
            if r.get("mid") == mid:
                out.append(r)
        return out

    def since(self, ts: float, evs: set[str]) -> list[dict]:
        """События видов ``evs`` новее ``ts`` (сводка сбоев владельцу, alerts.py)."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for x in lines:
            try:
                r = json.loads(x)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("ev") in evs and float(r.get("ts") or 0) > ts:
                out.append(r)
        return out


def _ts(line: str) -> float:
    try:
        return float(json.loads(line).get("ts", 0))
    except (ValueError, AttributeError):
        return 0.0
