"""Корзина чатов: «Удалить» сессию или завершённый чат — журнал Claude Code переезжает в корзину пульта, а не
стирается. «Вернуть» — обратно на прежнее место.

Корзина — ``<данные>/trash/chats/<время>__<id сессии>/`` (0700): сам журнал ``<id>.jsonl``, папка ``<id>/`` рядом
с ним (у Claude Code там журналы субагентов и вывод инструментов) и ``meta.json`` — откуда взят, название, проект.
Запись старше ``KEEP_DAYS`` (30 дней) удаляется окончательно — вместе с журналом и папкой субагентов: ``purge``
раз в час из фонового цикла панели и перед показом корзины. За ``WARN_DAYS`` (3 дня) список предупреждает
(``days_left``). Пути в ответах API нет — только id корзины, название и время."""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import time
from pathlib import Path

from gas_pult import transcripts

KEEP_DAYS = 30                                                  # дней в корзине до окончательного удаления
WARN_DAYS = 3                                                   # за столько дней список предупреждает
DAY = 86400
TID = re.compile(r"^\d{8}-\d{6}__[0-9a-f-]{36}(-\d+)?$")       # id в корзине: время и id сессии


def base(data: Path) -> Path:
    return data / "trash" / "chats"


def put(data: Path, f: Path, title: str = "", project: str = "") -> dict:
    """Журнал ``f`` (и папку ``<id>/`` рядом) — в корзину. Возвращает запись корзины (без путей)."""
    sid = transcripts.valid_sid(f.stem)
    if not sid or not f.is_file():
        raise LookupError("журнала чата нет — нечего переносить")
    root = base(data)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    tid = f"{time.strftime('%Y%m%d-%H%M%S')}__{sid}"
    dst = root / tid
    n = 1
    while dst.exists():                                  # два удаления одного чата за секунду
        n += 1
        dst = root / f"{tid}-{n}"
    dst.mkdir(mode=0o700)
    rec = {"sid": sid, "src": str(f), "title": title, "project": project, "at": int(time.time())}
    (dst / "meta.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    shutil.move(str(f), str(dst / f.name))
    side = f.with_suffix("")
    if side.is_dir():
        shutil.move(str(side), str(dst / side.name))
    return public(dst.name, rec)


def public(tid: str, rec: dict, now: float | None = None) -> dict:
    """Запись для API. ``purge_at`` — когда удалится окончательно; ``days_left`` — сколько дней осталось (вверх,
    не меньше 0); ``warn`` — осталось не больше ``WARN_DAYS``."""
    at = int(rec.get("at") or 0)
    purge_at = at + KEEP_DAYS * DAY
    left = max(0, -(-(purge_at - int(time.time() if now is None else now)) // DAY))     # ceil
    return {"id": tid, "sid": rec.get("sid", ""), "title": rec.get("title", ""), "project": rec.get("project", ""),
            "at": rec.get("at"), "purge_at": purge_at, "days_left": left, "warn": left <= WARN_DAYS}


def _meta(d: Path) -> dict | None:
    with contextlib.suppress(OSError, ValueError):
        rec = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if isinstance(rec, dict) and transcripts.valid_sid(rec.get("sid")):
            return rec
    return None


def _at(d: Path, rec: dict) -> int:
    """Когда удалён: ``at`` из ``meta.json``; нет — время папки."""
    with contextlib.suppress(TypeError, ValueError):
        if at := int(rec.get("at") or 0):
            return at
    with contextlib.suppress(OSError):
        return int(d.stat().st_mtime)
    return 0


def listing(data: Path, now: float | None = None) -> list[dict]:
    """Что в корзине — новые сверху."""
    out = []
    with contextlib.suppress(OSError):
        for d in base(data).iterdir():
            if d.is_dir() and (rec := _meta(d)):
                out.append(public(d.name, {**rec, "at": _at(d, rec)}, now))
    out.sort(key=lambda x: -(x["at"] or 0))
    return out


def restore(data: Path, tid: str) -> dict:
    """«Вернуть»: журнал (и папку рядом) — на прежнее место. Там уже есть файл с тем же id — не затираем."""
    tid = str(tid or "")
    if not TID.match(tid):
        raise LookupError("в корзине такого чата нет")
    d = base(data) / tid
    rec = _meta(d) if d.is_dir() else None
    if not rec:
        raise LookupError("в корзине такого чата нет")
    src = Path(rec["src"])
    if src.exists():
        raise ValueError("на прежнем месте уже есть журнал с тем же id — вернуть нельзя, не затерев его")
    src.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.move(str(d / src.name), str(src))
    side = d / src.stem
    if side.is_dir() and not src.with_suffix("").exists():
        shutil.move(str(side), str(src.with_suffix("")))
    (d / "meta.json").unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        os.rmdir(d)
    return public(tid, rec)


def purge(data: Path, now: float | None = None) -> list[str]:
    """Окончательно удалить записи старше ``KEEP_DAYS``: журнал, папку субагентов и ``meta.json``. Только папки
    корзины с id нашего вида и ``meta.json``; ссылки внутри не разыменовываются (``shutil.rmtree``). Возвращает id
    удалённых."""
    now = time.time() if now is None else now
    gone = []
    with contextlib.suppress(OSError):
        for d in base(data).iterdir():
            if d.is_symlink() or not d.is_dir() or not TID.match(d.name) or not (rec := _meta(d)):
                continue
            if now - _at(d, rec) >= KEEP_DAYS * DAY:
                try:
                    shutil.rmtree(d)
                except OSError as e:
                    print("корзина чатов:", d.name, e, flush=True)
                    continue
                gone.append(d.name)
    return gone
