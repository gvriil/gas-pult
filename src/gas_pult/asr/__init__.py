"""Потоковое распознавание речи (задача 46): клиент службы ``gas-pult-asr`` и её протокол. Только stdlib.

Служба (``python -m gas_pult.asr.service``) живёт отдельным процессом в своём venv (``gas-pult asr install``): движок
T-one (ONNX, CPU) грузится один раз и держится в памяти. Связь — unix-сокет ``<данные пульта>/asr/asr.sock`` (папка
0700), без сети.

Протокол — кадры ``[тип: 1 байт][длина: 4 байта, big-endian][данные]``: ``J`` — объект JSON (UTF-8), ``A`` — звук
PCM 16 бит little-endian моно. Клиент: ``{"op": "start", "rate": 16000, "partials": true}`` → служба:
``{"ready": true}`` (или ``{"error", "code": "busy"}``); затем кадры ``A`` — служба отвечает ``{"partial": "…"}``, когда
текст изменился; ``{"op": "end"}`` → ``{"final": "…", "lag_ms": …}``. ``{"op": "ping"}`` → ``{"ok": true, …}``.

Нет службы, занята или упала — ``Unavailable``: пульт идёт нынешним путём (облако или whisper, ``voice.transcribe``).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import struct
import subprocess
from pathlib import Path

from gas_pult import config

SOCKET_ENV = "GAS_PULT_ASR_SOCKET"        # другой сокет (проверка, второй пульт)
UNIT = "gas-pult-asr.service"
HDR = struct.Struct(">cI")
MAX_FRAME = 1 << 20                        # кусок звука — десятки КБ; больше 1 МБ — ошибка протокола
RATES = (8000, 16000, 48000)               # частоты, которые служба понижает до 8 кГц сама
CHUNK = 32000                              # по столько байт файл уходит в службу (1 с при 16 кГц)


class Unavailable(RuntimeError):
    """Службы нет, она занята или ответила не по протоколу — нужен запасной путь."""


def home(data: Path | None = None) -> Path:
    """Папка службы: venv, модель, сокет."""
    return (data or config.data_dir()) / "asr"


def socket_path(data: Path | None = None) -> Path:
    if env := os.environ.get(SOCKET_ENV):
        return Path(env)
    return home(data) / "asr.sock"


# ---------- кадры ----------

def send(sock: socket.socket, kind: bytes, data: bytes) -> None:
    sock.sendall(HDR.pack(kind, len(data)) + data)


def send_json(sock: socket.socket, obj: dict) -> None:
    send(sock, b"J", json.dumps(obj, ensure_ascii=False).encode())


def _exact(sock: socket.socket, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        part = sock.recv(n - len(buf))
        if not part:
            if buf:
                raise ValueError("кадр оборван")
            return None
        buf += part
    return bytes(buf)


def recv(sock: socket.socket) -> tuple[bytes, object] | None:
    """Следующий кадр: (b"J", dict) или (b"A", bytes); конец соединения — None."""
    head = _exact(sock, HDR.size)
    if head is None:
        return None
    kind, n = HDR.unpack(head)
    if kind not in (b"J", b"A") or n > MAX_FRAME:
        raise ValueError("неверный кадр")
    data = _exact(sock, n) if n else b""
    if data is None:
        raise ValueError("кадр оборван")
    if kind == b"J":
        obj = json.loads(data.decode())
        if not isinstance(obj, dict):
            raise ValueError("ожидался объект JSON")
        return kind, obj
    return kind, data


# ---------- клиент ----------

class Stream:
    """Один поток распознавания. Открыть не удалось — ``Unavailable``."""

    def __init__(self, rate: int = 16000, partials: bool = True, path: Path | None = None, timeout: float = 3.0):
        path = path or socket_path()
        if rate not in RATES:
            raise ValueError(f"частота {rate} Гц не поддерживается")
        if not path.exists():
            raise Unavailable("служба распознавания не запущена")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        try:
            self.sock.connect(str(path))
            send_json(self.sock, {"op": "start", "rate": rate, "partials": partials})
            r = recv(self.sock)
        except (OSError, ValueError) as e:
            self.close()
            raise Unavailable(f"служба распознавания не отвечает: {e}") from None
        if not r or r[0] != b"J" or not r[1].get("ready"):
            self.close()
            raise Unavailable((r and r[1].get("error")) or "служба распознавания не готова")

    def audio(self, pcm: bytes) -> None:
        if pcm:
            send(self.sock, b"A", pcm)

    def end(self) -> None:
        send_json(self.sock, {"op": "end"})

    def events(self, timeout: float | None = None):
        """Ответы службы по одному: ``{"partial"}``, ``{"final"}`` (последний) или ``{"error"}``."""
        if timeout is not None:
            self.sock.settimeout(timeout)
        while True:
            r = recv(self.sock)
            if r is None:
                raise Unavailable("служба распознавания закрыла соединение")
            if r[0] != b"J":
                continue
            yield r[1]
            if "final" in r[1] or "error" in r[1]:
                return

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def transcribe_pcm(pcm: bytes, rate: int = 16000, path: Path | None = None, timeout: float = 60) -> str:
    """Готовая запись целиком → текст (бот, запасной ``/api/stt``)."""
    try:
        with Stream(rate, partials=False, path=path) as st:
            st.sock.settimeout(timeout)
            for i in range(0, len(pcm), CHUNK):
                st.audio(pcm[i:i + CHUNK])
            st.end()
            for ev in st.events(timeout):
                if "error" in ev:
                    raise Unavailable(str(ev["error"]))
                if "final" in ev:
                    return str(ev["final"]).strip()
    except OSError as e:                      # оборвалось посреди записи — тоже запасной путь
        raise Unavailable(f"служба распознавания: {e}") from None
    return ""


def ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return shutil.which("ffmpeg")


def decode(src: Path | bytes, rate: int = 16000, timeout: float = 60) -> bytes:
    """Любой звук (ogg, webm, mp4, wav) → PCM 16 бит моно ``rate`` Гц через ffmpeg; нет ffmpeg — ``Unavailable``."""
    exe = ffmpeg()
    if not exe:
        raise Unavailable("нет ffmpeg для перекодирования звука")
    arg, data = (str(src), None) if isinstance(src, Path) else ("pipe:0", src)
    try:
        r = subprocess.run([exe, "-loglevel", "error", "-i", arg, "-f", "s16le", "-ac", "1", "-ar", str(rate), "-"],
                           input=data, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Unavailable(f"ffmpeg: {e}") from None
    if r.returncode != 0:
        raise Unavailable("ffmpeg не разобрал запись")
    return r.stdout


def transcribe(src: Path | bytes, data: Path | None = None, timeout: float = 60) -> str:
    """Файл или байты голосового → текст службой; службы нет — ``Unavailable``."""
    path = socket_path(data)
    if not path.exists():                     # без службы и ffmpeg не запускаем
        raise Unavailable("служба распознавания не запущена")
    return transcribe_pcm(decode(src, 16000, timeout), 16000, path, timeout)


def status(data: Path | None = None, timeout: float = 2.0) -> dict | None:
    """Состояние службы (``ping``) или None, если её нет."""
    path = socket_path(data)
    if not path.exists():
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(path))
            send_json(s, {"op": "ping"})
            r = recv(s)
    except (OSError, ValueError):
        return None
    return r[1] if r and r[0] == b"J" else None
