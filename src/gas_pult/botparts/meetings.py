"""Протоколы встреч в боте (GAS-36): куски записи и текста, «Готово — протокол» → чат «Встречи».

Часть класса ``bot.Pult`` (модульный монолит, docs/MONOLITH-PLAN.md п.3.3): методы перенесены как есть, ``self`` —
тот же ``Pult``. Хранилище встреч — ``self.meetings`` (``meetings.Store``), модуль ``meetings`` — разбор и протокол.
"""

from __future__ import annotations

import threading
import time
from typing import ClassVar

from gas_pult import drive_inbox, meetings, voice
from gas_pult.telegram import kb


class MeetingsPart:
    """Протоколы встреч (примесь к ``Pult``)."""

    # ---------- протоколы встреч (GAS-36, meetings.py) ----------
    MT_KB: ClassVar[dict] = {"consent": [[("✅ Предупредил — начать", "mt:ok"), ("✖️ Отмена", "mt:cancel")]],
             "open": [[("📝 Готово — протокол", "mt:done"), ("✖️ Отменить встречу", "mt:cancel")]],
             "stale": [[("➕ Это продолжение", "mt:cont"), ("🆕 Новая встреча", "mt:new")]]}

    def meeting_start(self, chat: int):
        if self.meetings.current(chat):
            return self.send(chat, "Встреча уже идёт — присылайте куски. Всё — «Готово — протокол».",
                             reply_markup=kb(self.MT_KB["open"]))
        self.send(chat, "📝 Протокол встречи.\n\n" + meetings.CONSENT, reply_markup=kb(self.MT_KB["consent"]))

    def meeting_piece(self, chat: int, m: dict):
        if self.meetings.stale(chat):
            self.mt_wait[chat] = m
            return self.send(chat, f"Встреча начата больше {meetings.CONTINUE_H} ч назад. Это продолжение или новая?",
                             reply_markup=kb(self.MT_KB["stale"]))
        f = m.get("voice") or m.get("audio") or m.get("video_note") or m.get("document")
        if not f:
            t = (m.get("text") or m.get("caption") or "").strip()
            if not t:
                return self.send(chat, "Пришлите голосовое, аудиофайл или текст встречи.")
            n = len(self.meetings.add(chat, t, "текст")["pieces"])
            return self.send(chat, f"✍ Кусок {n} добавлен (текст).", reply_markup=kb(self.MT_KB["open"]))
        self.react(m, "✍")
        threading.Thread(target=self._meeting_audio, args=(chat, f), daemon=True).start()

    def _meeting_audio(self, chat: int, f: dict):
        try:
            path = self.api.download(f["file_id"], self.cfg.data / "inbox", f.get("file_name") or "meeting.ogg")
            text = voice.transcribe_any(path, self.cfg.whisper_model, 40 * 60, data=self.cfg.data)
            if not text:
                return self.send(chat, "Не разобрал запись — пришлите ещё раз или текстом.")
            n = len(self.meetings.add(chat, text, "запись", file=str(path))["pieces"])
            self.send(chat, f"✍ Кусок {n}: {text[:120]}{'…' if len(text) > 120 else ''}",
                      reply_markup=kb(self.MT_KB["open"]))
        except Exception as e:
            self.send(chat, f"Не разобрал запись: {e}. Файл пришлите ещё раз.")

    def meeting_button(self, chat: int, arg: str):
        if arg == "ok":
            self.meetings.open(chat)
            self.send(chat, "▶️ Встреча начата. Присылайте голосовые, аудиофайлы из Диктофона или текст — кусками "
                            "можно. Скажите вслух «Клод, запиши …» — это станет поручением в протоколе; «Клод, "
                            "отправь …» — черновик, отправка после «Да». Всё — «Готово — протокол».",
                      reply_markup=kb(self.MT_KB["open"]))
            if m := self.mt_wait.pop(chat, None):
                self.meeting_piece(chat, m)
            return None
        if arg == "cancel":
            self.mt_wait.pop(chat, None)
            self.meetings.close(chat)
            return self.send(chat, "Встреча отменена — куски удалены.")
        if arg == "cont":
            mt = self.meetings.current(chat)
            if mt:
                mt["started"] = time.time() - 60             # продолжение — счётчик «давно» заново
                with self.meetings.lock:
                    d = self.meetings._load()
                    d[str(chat)] = mt
                    self.meetings._save(d)
            if m := self.mt_wait.pop(chat, None):
                self.meeting_piece(chat, m)
            return None
        if arg == "new":
            self.meeting_done(chat)
            return self.meeting_start(chat)
        if arg == "done":
            return self.meeting_done(chat)
        return None

    def meeting_done(self, chat: int):
        mt = self.meetings.close(chat)
        if not mt or not mt["pieces"]:
            return self.send(chat, "Во встрече нет ни одного куска — протокол не из чего делать.")
        drive = drive_inbox.drive_root(self.cfg.drive_root)
        folder, on_drive = meetings.save(mt, drive, self.cfg.data)
        self.send(chat, f"📁 Расшифровка ({len(mt['pieces'])} кусков) — {'на Диске' if on_drive else 'на сервере'}: "
                        f"{folder}\nДелаю протокол в чате «Встречи» — ответ придёт сюда.")
        root = self.cfg.roots()[0] / "meetings"
        root.mkdir(parents=True, exist_ok=True)
        self.open_session(chat, "meetings", str(root), first=meetings.prompt(folder, on_drive, meetings.commands(mt),
                                                                             meetings.saved_dur(folder)))
