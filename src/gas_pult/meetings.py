"""Протоколы встреч (GAS-36, MVP; владелец 19.11: «быстро и лучше практик»; исследование штаба —
portfolio-hq/products/meeting-notes-research-2026-11-19.md).

Встреча — куски из любого канала (голосовое, аудиофайл из Диктофона iPhone через «Поделиться», текст), склеенные в
одну. Перед первой записью — напоминание о согласии участников (без отметки «Предупредил» встреча не начинается).
«Готово» — расшифровка (и аудио) ложатся в папку на Диске клиента ``Встречи/ГГГГ-ММ-ДД ЧЧ-ММ встреча`` (Диска нет —
локально в данных пульта, с пометкой); агент в чате «Встречи» делает протокол по формату и предлагает действия:
разослать участникам, в календарь, в заметки — каждое только после «Да». Запись в браузере при заблокированном
экране не обещаем: для длинной встречи — Диктофон iPhone и файл.

Хранение состояния — ``<данные>/meetings.json`` (0600): только открытые встречи по чату, тексты кусков.

**Поручения вслух** (владелец 20.11): во время записи человек говорит «Клод, запиши …» — фрагмент становится отдельным
пунктом-поручением протокола (дословно, с отметкой времени); «Клод, … отправь …» — агент готовит черновик отправки,
отправка — только после «Да». Слова-обращения: Клод, Клауд, Claude, Гаврила (так их пишет распознавание речи).
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path

from gas_pult.config import write_private

CONTINUE_H = 3                 # встреча открыта дольше — новый кусок спрашивает «продолжение или новая»
CONSENT = ("Перед записью предупредите участников, например: «Я записываю встречу, чтобы сделать протокол». "
           "Для длинной встречи включите Диктофон iPhone и пришлите файл сюда («Поделиться» → Telegram → бот): "
           "запись в браузере при заблокированном экране может остановиться.")


class Store:
    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock, self.lock = Path(path), clock, threading.Lock()

    def _load(self) -> dict:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, d: dict):
        write_private(self.path, json.dumps(d, ensure_ascii=False))

    def current(self, chat) -> dict | None:
        return self._load().get(str(chat))

    def open(self, chat) -> dict:
        """Новая встреча (согласие отмечено — «Предупредил»)."""
        now = self.clock()
        m = {"id": time.strftime("%Y%m%d-%H%M%S", time.localtime(now)), "started": now, "consent": True,
             "pieces": [], "files": []}
        with self.lock:
            d = self._load()
            d[str(chat)] = m
            self._save(d)
        return m

    def stale(self, chat) -> bool:
        m = self.current(chat)
        return bool(m) and self.clock() - m["started"] > CONTINUE_H * 3600

    def add(self, chat, text: str, kind: str, file: str = "") -> dict:
        with self.lock:
            d = self._load()
            m = d.get(str(chat))
            if not m:
                raise LookupError("встречи нет — начните: «Протокол встречи»")
            m["pieces"].append({"at": self.clock(), "kind": kind, "text": text.strip()})
            if file:
                m["files"].append(file)
            self._save(d)
        return m

    def close(self, chat) -> dict | None:
        with self.lock:
            d = self._load()
            m = d.pop(str(chat), None)
            self._save(d)
        return m


def transcript(m: dict) -> str:
    """Расшифровка встречи: куски по порядку, с отметкой времени от начала."""
    out = []
    for p in m["pieces"]:
        mm = int((p["at"] - m["started"]) // 60)
        out.append(f"[{mm // 60:02d}:{mm % 60:02d}] ({p['kind']}) {p['text']}")
    return "\n\n".join(out)


WAKE = r"(?:клод|клауд|claude|гаврил[аы]?)"
# обращение → «запиши» или «отправь» → текст до конца фразы (точка, «!», «?», перевод строки)
CMD = re.compile(WAKE + r"[\s,:—–-]+(запиши|отправь)\b[\s,:—–-]*(.*?)(?=[.!?…](?:\s|$)|\n|$)", re.I | re.S)
SEND = re.compile(r"[\s,]*(?:и\s+)?отправь\b", re.I)


def commands(m: dict) -> list[dict]:
    """Поручения вслух: [{at: "ЧЧ:ММ" от начала, kind: note | send, text}] — по порядку."""
    out = []
    for p in m.get("pieces", []):
        mm = int((p["at"] - m["started"]) // 60)
        for verb, text in CMD.findall(p.get("text", "")):
            text = text.strip(" ,:—–-")
            kind = "send" if verb.lower() == "отправь" or SEND.search(text) else "note"
            text = SEND.sub("", text).strip(" ,:—–-") if verb.lower() == "запиши" else text
            if text:
                out.append({"at": f"{mm // 60:02d}:{mm % 60:02d}", "kind": kind, "text": text})
    return out


def commands_md(cmds: list[dict]) -> str:
    """Файл «поручения.md» рядом с расшифровкой: что сказали записать и что — отправить (после «Да»)."""
    head = "# Поручения, сказанные вслух\n\n«Отправить» — только черновик; отправка — после «Да».\n"
    return head + "\n".join(f"- [{c['at']}] {'Отправить' if c['kind'] == 'send' else 'Записать'}: {c['text']}"
                             for c in cmds) + "\n"


def folder_for(m: dict, drive: Path | None, data: Path) -> tuple[Path, bool]:
    """Папка встречи: на Диске клиента ``Встречи/ГГГГ-ММ-ДД ЧЧ-ММ встреча`` или локально. (папка, на Диске ли)."""
    name = time.strftime("%Y-%m-%d %H-%M", time.localtime(m["started"])) + " встреча"
    if drive and drive.is_dir():
        return drive / "Встречи" / name, True
    return data / "meetings" / name, False


def save(m: dict, drive: Path | None, data: Path) -> tuple[Path, bool]:
    """Расшифровка — в папку встречи; аудио — туда же и с сервера прочь, когда папка на Диске."""
    d, on_drive = folder_for(m, drive, data)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    (d / "расшифровка.txt").write_text(transcript(m) + "\n", encoding="utf-8")
    if cmds := commands(m):
        (d / "поручения.md").write_text(commands_md(cmds), encoding="utf-8")
    for f in m.get("files", []):
        src = Path(f)
        if src.is_file():
            dst = d / re.sub(r"[^\w.\- ]", "_", src.name)
            (shutil.move if on_drive else shutil.copy2)(str(src), dst)
    return d, on_drive


def prompt(folder: Path, on_drive: bool, cmds: list[dict] | None = None) -> str:
    """Задание агенту в чате «Встречи»: протокол по формату, потом действия — каждое после «Да»."""
    where = "на Диске" if on_drive else "на сервере (Диск не подключён — скажите об этом в итоге)"
    said = ""
    if cmds:
        said = ("\nПоручения, сказанные вслух («Клод, запиши / отправь»), — отдельным разделом «Поручения» в начале "
                "протокола, дословно, с отметкой времени; не теряй и не перефразируй:\n"
                + "\n".join(f"- [{c['at']}] {'Отправить' if c['kind'] == 'send' else 'Записать'}: {c['text']}"
                             for c in cmds)
                + "\nДля «Отправить» подготовь черновик (кому, текст) и спроси «Да / Нет / Позже» — сам не отправляй.")
    head = said.lstrip("\n") + ("\n\n" if said else "")
    return head + (f"Протокол встречи. Расшифровка: «{folder / 'расшифровка.txt'}» ({where}). Сделай протокол простым "
            "языком и сохрани рядом как «протокол.md»:\n1. Тема и дата.\n2. Участники — предложи по тексту и спроси "
            "меня вопросом с вариантами, кого отметить.\n3. Решения — по пунктам, с отметкой времени.\n4. Задачи: "
            "что, кто, срок.\n5. Открытые вопросы.\nПотом спроси вопросом с вариантами, что сделать: «Разослать "
            "участникам» (черновик письма), «В календарь» (следующая встреча и сроки, если календарь подключён), "
            "«В заметки» (Apple через мост, Notion или Диск — что подключено), «Сохранить». Письма, события и "
            "заметки — только после моего «Да».")
