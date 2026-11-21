"""«Отзыв» из панели (штаб 21.11): текст (или голос — диктовкой клавиатуры) и снимок экрана по желанию → в задачи
штаба. Плюс счётчик «где застревают» — в отчёте функций (features.py, id экранов без текста).

Отзыв — файл ``<данные>/feedback/<время>-<случайное>.json`` (0600) и снимок рядом (png, jpeg или webp, до 4 МБ);
ночной UI-обзор читает эту папку. В задачи владельца ложится задача «Отзыв: …» со ссылкой на файл, владельцу —
сообщение бота. В файле — кто (id и имя), экран (id), текст; паролей и переписки нет.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import time
from pathlib import Path

DIR = "feedback"
MAX_TEXT = 4000
MAX_SHOT = 4 * 1024 * 1024
SCREEN = re.compile(r"^[a-z][a-z0-9_.:-]{0,60}$")
SHOT = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=\s]+)$")
MAGIC = {"png": b"\x89PNG", "jpeg": b"\xff\xd8\xff", "webp": b"RIFF"}


def _write(path: Path, data: bytes):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def shot_bytes(url: str) -> tuple[str, bytes]:
    """Снимок из data: URL панели → (расширение, байты); не картинка или больше 4 МБ — ValueError."""
    m = SHOT.match(str(url or ""))
    if not m:
        raise ValueError("снимок — картинка png, jpeg или webp")
    kind = m.group(1)
    if len(m.group(2)) > MAX_SHOT * 4 // 3 + 16:
        raise ValueError("снимок больше 4 МБ")
    data = base64.b64decode(m.group(2))
    if not data.startswith(MAGIC[kind]):
        raise ValueError("снимок — не картинка")
    return ("jpg" if kind == "jpeg" else kind), data


def save(data_dir: Path, uid, name: str, text: str, screen: str = "", shot: str = "") -> dict:
    text = str(text or "").strip()[:MAX_TEXT]
    if not text and not shot:
        raise ValueError("напишите, что не так или что улучшить, или приложите снимок")
    screen = screen if SCREEN.match(str(screen or "")) else ""
    d = Path(data_dir) / DIR
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = time.strftime("%Y-%m-%d-%H%M%S") + "-" + secrets.token_hex(3)
    rec = {"at": int(time.time()), "uid": uid, "name": str(name or "")[:80], "screen": screen, "text": text, "shot": ""}
    if shot:
        ext, data = shot_bytes(shot)
        rec["shot"] = f"{base}.{ext}"
        _write(d / rec["shot"], data)
    rec["file"] = str(d / f"{base}.json")
    _write(d / f"{base}.json", json.dumps(rec, ensure_ascii=False, indent=1).encode())
    return rec


def task(rec: dict) -> dict:
    """Задача владельцу/штабу по отзыву."""
    head = " ".join(rec["text"].split())[:120] or "снимок экрана без текста"
    return {"title": f"Отзыв: {head}", "kind": "check", "link": rec["file"],
            "next": f"Разобрать отзыв ({rec['name'] or 'без имени'}, экран {rec['screen'] or '—'}) и решить, "
                    "что менять"}
