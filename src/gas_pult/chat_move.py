"""«Перенести в проект…» (владелец 22.11: «очень важно добавить возможность переносить чаты из проекта в проект»).

Чат Claude Code продолжается в папке другого проекта с той же историей:

1. окно закрывается штатно (как «Перезапустить»: Claude сам дописывает журнал и выходит);
2. журнал ``<id>.jsonl`` и папка ``<id>/`` рядом (журналы субагентов, вывод инструментов) копируются в папку Claude
   Code новой папки проекта — ``transcripts.project_dir(<новая папка>, <папка Claude окна>)``: тот же код, которым
   пульт ищет журналы (все знаки пути, кроме латиницы и цифр, — «-»);
3. окно открывается в новой папке с ``claude --resume <id>`` (модель, поставщик и усилие — как у перезапуска);
4. старый журнал — в корзину чатов пульта (``chat_trash.put``): вернуть можно, не стирается.

Поле ``cwd`` в старых записях журнала не меняем: это история (команды шли в прежней папке); Claude Code ищет
разговор по файлу ``<id>.jsonl`` в папке журналов текущей папки, а ``cwd`` пишет в каждую запись заново — в одном
журнале бывает несколько разных ``cwd`` (``cd`` в другую папку посреди разговора), и ``--resume`` это не мешает.

Идёт ход — не прерываем: перенос ждёт в ``<данные>/chat-moves.json`` (окно → проект), фоновый цикл панели
(``Panel.move_tick``, раз в минуту) выполняет его, когда окно освободилось. Здесь — только файлы и очередь; окна и
проекты — в ``panel/projects.py``.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from gas_pult import store as jstore
from gas_pult import transcripts
from gas_pult.config import write_private

FILE = "chat-moves.json"
PENDING_TTL = 6 * 3600              # с: отложенный перенос дольше этого не ждёт (ход шёл бы часами — что-то не так)
BUSY = ("working", "thinking", "started", "sent", "delivered", "queued")   # фазы хода (activity.combine)


def busy(act: dict) -> bool:
    """Идёт ход: та же строка статуса, что у панели и бота (``activity.combine``). «Ждёт ответа» — не ход."""
    return (act or {}).get("phase") in BUSY


def copy_journal(f: Path, dst_dir: Path) -> Path:
    """Копия журнала ``f`` (и папки ``<id>/`` рядом) в ``dst_dir``. Там уже есть журнал с этим id — отказ: чужой
    разговор не перезаписываем. Возвращает путь копии."""
    sid = transcripts.valid_sid(f.stem)
    if not sid or not f.is_file():
        raise LookupError("журнала чата нет — переносить нечего")
    dst = dst_dir / f.name
    if dst.resolve() == f.resolve():
        raise ValueError("чат уже в этой папке")
    if dst.exists():
        raise ValueError("в новой папке уже есть журнал этого разговора — перенос остановлен, ничего не изменено")
    dst_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = dst_dir / f".{f.name}.{os.getpid()}.part"
    shutil.copy2(f, tmp)
    os.replace(tmp, dst)                       # Claude Code не увидит половину файла
    side = f.with_suffix("")
    if side.is_dir() and not (dst_dir / side.name).exists():
        shutil.copytree(side, dst_dir / side.name, symlinks=True)
    return dst


class Pending:
    """Отложенные переносы: ``{окно: {"project": id, "at": когда, "by": кто}}`` под замком (панель и CLI)."""

    def __init__(self, file: Path):
        self.file = Path(file)

    def read(self) -> dict:
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return d if isinstance(d, dict) else {}

    def _write(self, d: dict):
        write_private(self.file, json.dumps(d, ensure_ascii=False, indent=1) + "\n")

    def add(self, wid: str, project: str, by: str = "") -> dict:
        with jstore.locked(self.file):
            d = self.read()
            d[wid] = rec = {"project": project, "at": int(time.time()), "by": by}
            self._write(d)
            return rec

    def get(self, wid: str) -> dict | None:
        return self.read().get(wid)

    def take(self, wid: str) -> dict | None:
        """Забрать запись (её больше никто не выполнит второй раз)."""
        with jstore.locked(self.file):
            d = self.read()
            rec = d.pop(wid, None)
            if rec is not None:
                self._write(d)
            return rec

    def put_back(self, wid: str, rec: dict):
        with jstore.locked(self.file):
            d = self.read()
            d.setdefault(wid, rec)
            self._write(d)


class Busy(ValueError):
    """Идёт ход, а ждать нельзя (CLI без ``--wait`` спросит сам)."""


class Failed(ValueError):
    """Перенос не удался после закрытия окна: чат снова открыт на прежнем месте (``wid`` — его новое окно)."""

    def __init__(self, text: str, wid: str = ""):
        super().__init__(text)
        self.wid = wid
