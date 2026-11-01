"""Каналы связи: общий интерфейс ``Channel`` и первая реализация — ``TelegramChannel``.

Бот пока работает с ``telegram.Api`` напрямую; интерфейс описывает тот минимум, которым он пользуется: отправить
текст с кнопками, поправить сообщение, ответить на нажатие, отправить файл или голос, скачать вложение и получить
обновления. Новый канал (MAX, VK, почта…) — класс с теми же методами; путь перевода бота — в ``docs/CHANNELS.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable

from gas_pult.telegram import Api


@dataclass(frozen=True)
class Button:
    """Кнопка под сообщением. Ровно одно из: ``data`` (нажатие вернётся боту), ``url`` (ссылка), ``web_app``
    (Mini App по адресу). Канал без нужного вида кнопок вправе показать её ссылкой или текстом."""
    text: str
    data: str = ""
    url: str = ""
    web_app: str = ""


Keyboard = list[list[Button]]


def buttons(rows) -> Keyboard:
    """Клавиатура из [[(подпись, данные), …], …] — тот же вид, что у ``telegram.kb``."""
    return [[Button(t, d) for t, d in row] for row in rows]


@dataclass(frozen=True)
class Caps:
    """Что умеет канал. Бот смотрит сюда, прежде чем слать кнопки, править сообщение или голос."""
    buttons: bool = False        # кнопки под сообщением с ответом боту
    edit: bool = False           # править уже отправленное сообщение
    voice: bool = False          # голосовые: принимать и отправлять
    files: bool = False          # файлы в обе стороны
    mini_app: bool = False       # кнопка, открывающая панель внутри мессенджера
    max_text: int = 4000         # длина одного сообщения; длиннее — бот режет сам


@dataclass(frozen=True)
class Attachment:
    kind: str                    # voice · audio · photo · document · video
    file_id: str                 # идентификатор у канала — для ``Channel.download``
    name: str = ""


@dataclass(frozen=True)
class Incoming:
    """Входящее событие в нейтральном виде: сообщение или нажатие кнопки."""
    channel: str
    chat: int | str
    user: int | str
    text: str = ""
    button: str = ""             # ``Button.data`` нажатой кнопки; пусто — это сообщение
    callback_id: str = ""        # чем подтвердить нажатие (``Channel.answer``)
    message_id: int | str | None = None   # сообщение (для нажатия — то, под которым кнопка)
    attachment: Attachment | None = None
    raw: dict = field(default_factory=dict, compare=False, repr=False)   # как пришло от канала


@runtime_checkable
class Channel(Protocol):
    name: str
    caps: Caps

    def send_text(self, chat, text: str, keyboard: Keyboard | None = None) -> int | str | None:
        """Отправить текст; вернуть id сообщения (для правки), если канал его даёт."""

    def edit_text(self, chat, message_id, text: str, keyboard: Keyboard | None = None) -> None: ...

    def answer(self, callback_id: str, text: str = "") -> None:
        """Подтвердить нажатие кнопки (у Telegram без этого крутятся часики)."""

    def send_file(self, chat, name: str, data: bytes, kind: str = "document") -> None:
        """kind: document · voice (голосовое) · audio (аудиофайл)."""

    def download(self, attachment: Attachment, dst_dir: Path) -> Path: ...

    def poll(self, timeout: int = 60) -> list[Incoming]:
        """Дождаться новых событий (long polling); канал с вебхуком отдаёт накопленное."""


class TelegramChannel:
    """Telegram через существующий ``telegram.Api``: перевод нейтральных вызовов в методы Bot API."""

    name = "telegram"
    caps = Caps(buttons=True, edit=True, voice=True, files=True, mini_app=True, max_text=4000)
    FILES: ClassVar[dict[str, tuple[str, str]]] = {
        "document": ("sendDocument", "document"), "voice": ("sendVoice", "voice"), "audio": ("sendAudio", "audio")}

    def __init__(self, api: Api):
        self.api = api
        self.offset: int | None = None

    @staticmethod
    def markup(keyboard: Keyboard | None) -> dict:
        if not keyboard:
            return {}
        rows = [[{"text": b.text, **({"web_app": {"url": b.web_app}} if b.web_app else
                                     {"url": b.url} if b.url else {"callback_data": b.data})} for b in row]
                for row in keyboard]
        return {"reply_markup": {"inline_keyboard": rows}}

    def send_text(self, chat, text, keyboard=None):
        return (self.api("sendMessage", chat_id=chat, text=text or "—", **self.markup(keyboard)) or {}).get(
            "message_id")

    def edit_text(self, chat, message_id, text, keyboard=None):
        self.api("editMessageText", chat_id=chat, message_id=message_id, text=text, **self.markup(keyboard))

    def answer(self, callback_id, text=""):
        self.api("answerCallbackQuery", callback_query_id=callback_id, **({"text": text} if text else {}))

    def send_file(self, chat, name, data, kind="document"):
        method, field_ = self.FILES[kind]
        self.api(method, chat_id=chat, files={field_: (name, data)})

    def download(self, attachment, dst_dir):
        return self.api.download(attachment.file_id, dst_dir, attachment.name or None)

    def poll(self, timeout=60):
        out = []
        for u in self.api("getUpdates", timeout=timeout, **({"offset": self.offset} if self.offset else {})) or []:
            self.offset = u["update_id"] + 1
            if (ev := self.parse(u)) is not None:
                out.append(ev)
        return out

    @classmethod
    def parse(cls, u: dict) -> Incoming | None:
        """update Telegram → ``Incoming``; чего бот не обрабатывает (правки, каналы…) — None."""
        if q := u.get("callback_query"):
            m = q.get("message") or {}
            return Incoming(cls.name, (m.get("chat") or {}).get("id", q["from"]["id"]), q["from"]["id"],
                            button=q.get("data", ""), callback_id=q["id"], message_id=m.get("message_id"), raw=u)
        if not (m := u.get("message")):
            return None
        att = None
        for kind in ("voice", "audio", "document", "video"):
            if f := m.get(kind):
                att = Attachment(kind, f["file_id"], f.get("file_name", ""))
                break
        else:
            if photo := m.get("photo"):              # размеры по возрастанию — берём самый большой
                att = Attachment("photo", photo[-1]["file_id"])
        return Incoming(cls.name, m["chat"]["id"], (m.get("from") or {}).get("id", m["chat"]["id"]),
                        text=m.get("text") or m.get("caption") or "", message_id=m.get("message_id"),
                        attachment=att, raw=u)
