"""Минимальный клиент Telegram Bot API на стандартной библиотеке."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


class TelegramError(Exception):
    def __init__(self, method: str, description: str):
        super().__init__(f"{method}: {description}")
        self.description = description


class Api:
    def __init__(self, token: str):
        self._token = token
        self._base = f"https://api.telegram.org/bot{token}/"

    def __call__(self, method: str, files: dict | None = None, **params):
        params = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in params.items()}
        if files:                           # multipart — голосовые и аудио
            b = uuid.uuid4().hex
            body = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                            for k, v in params.items())
            for k, (fname, data) in files.items():
                body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'
                         f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + b"\r\n"
            req = urllib.request.Request(self._base + method, body + f"--{b}--\r\n".encode(),
                                         {"Content-Type": f"multipart/form-data; boundary={b}"})
        else:
            req = urllib.request.Request(self._base + method, urllib.parse.urlencode(params).encode())
        try:
            with urllib.request.urlopen(req, timeout=70) as r:
                return json.load(r)["result"]
        except urllib.error.HTTPError as e:
            try:
                desc = json.load(e).get("description", str(e))
            except ValueError:
                desc = str(e)
            raise TelegramError(method, desc) from None

    def download(self, file_id: str, dst_dir: Path, name: str | None = None) -> Path:
        path = self("getFile", file_id=file_id)["file_path"]
        dst_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        dst = dst_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.path.basename(name or path)}"
        urllib.request.urlretrieve(f"https://api.telegram.org/file/bot{self._token}/{path}", dst)
        return dst

    def redact(self, text: str) -> str:
        """Токен не должен попасть в лог даже внутри текста исключения."""
        return str(text).replace(self._token, "•••")


def kb(rows) -> dict:
    """Инлайн-клавиатура из [[(подпись, callback_data), …], …]."""
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}
