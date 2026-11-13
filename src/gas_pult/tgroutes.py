"""Какое окно у сообщения бота: ответ (reply) в Telegram уходит в окно исходного сообщения, а не в «активное».

Почему: владелец ведёт несколько сессий; ответ на «[штаб] …» уходил в то окно, которое последним стало активным
(#178, #179 P0.1). Порядок поиска окна для ответа:

1. Карта «чат, id сообщения → окно» (``tg_routes.json``, последние ``KEEP`` записей; переживает перезапуск бота).
2. Кнопки под исходным сообщением: в ``callback_data`` есть id окна (``act:@5``, ``key:@5|1``, ``scr:@5``…).
3. Заголовок «[имя окна]» в начале текста — только если окно с таким именем одно.

Нашли окно — пишем туда; reply на сообщение бота, окно которого не нашлось, — не подменяем «активным», а говорим.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

KEEP = 3000                                   # ~ несколько дней переписки владельца
WID = re.compile(r"(?:^|[:|])(@\d+)(?=$|[|:])")
HEAD = re.compile(r"^(?:→\s*)?\[([^\]\n]{1,80})\]")


class Routes:
    """Карта сообщений бота → окна tmux. Файл 0600, запись атомарная; ошибки диска не мешают отправке."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.cache: dict[str, str] | None = None

    def load(self) -> dict[str, str]:
        if self.cache is None:
            try:
                d = json.loads(self.path.read_text())
                self.cache = {str(k): str(v) for k, v in d.items()} if isinstance(d, dict) else {}
            except (OSError, ValueError):
                self.cache = {}
        return self.cache

    def bind(self, chat, mid, wid: str):
        if not (chat and mid and wid):
            return
        with self.lock:
            d = self.load()
            d.pop(f"{chat}:{mid}", None)
            d[f"{chat}:{mid}"] = wid
            while len(d) > KEEP:
                d.pop(next(iter(d)))
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                tmp = self.path.with_suffix(".tmp")
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    json.dump(d, f)
                os.replace(tmp, self.path)
            except OSError as e:
                print("routes:", e, flush=True)

    def get(self, chat, mid) -> str | None:
        with self.lock:
            return self.load().get(f"{chat}:{mid}")

    def moved(self, old: str, new: str):
        """Окно пересоздано (перезапуск сессии) — ответы на старые сообщения идут в новое окно."""
        with self.lock:
            d = self.load()
            hit = [k for k, v in d.items() if v == old]
        for k in hit:
            chat, _, mid = k.partition(":")
            self.bind(chat, mid, new)


def markup_wid(msg: dict) -> str | None:
    """Id окна из кнопок исходного сообщения (Telegram присылает их в ``reply_to_message``)."""
    for row in ((msg.get("reply_markup") or {}).get("inline_keyboard") or []):
        for b in row:
            data = str(b.get("callback_data") or "")
            _, _, arg = data.partition(":")
            if m := WID.search(arg):
                return m.group(1)
    return None


def head_name(msg: dict) -> str | None:
    """«[имя окна]» в начале текста исходного сообщения."""
    m = HEAD.match((msg.get("text") or msg.get("caption") or "").strip())
    return m.group(1).strip() if m else None
