"""WebSocket на стандартной библиотеке (RFC 6455) — только серверная сторона, для ``/api/stt/stream`` (задача 46).

Рукопожатие: ``accept(headers)`` → значение ``Sec-WebSocket-Accept`` или None, если это не запрос WebSocket.
Кадры: клиент обязан маскировать (иначе — ошибка протокола 1002), сервер не маскирует. Ping → pong, close → ответный
close. Расширения (сжатие) и подпротоколы не поддерживаются — браузер обходится без них.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import struct
import threading

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
CONT, TEXT, BINARY, CLOSE, PING, PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
MAX_MESSAGE = 1 << 20                      # сообщение панели — куски звука по ~3 КБ и короткий JSON


class ProtocolError(ValueError):
    def __init__(self, msg: str, code: int = 1002):
        super().__init__(msg)
        self.code = code


class Closed(Exception):
    """Соединение закрыто (кадром close или обрывом)."""

    def __init__(self, code: int = 1006, reason: str = ""):
        super().__init__(f"{code} {reason}".strip())
        self.code, self.reason = code, reason


def _tokens(v: str) -> set[str]:
    return {x.strip().lower() for x in (v or "").split(",")}


def accept(headers) -> str | None:
    """Проверить рукопожатие клиента; годится — ответ для ``Sec-WebSocket-Accept``."""
    if "websocket" not in _tokens(headers.get("Upgrade", "")):
        return None
    if "upgrade" not in _tokens(headers.get("Connection", "")):
        return None
    if headers.get("Sec-WebSocket-Version", "").strip() != "13":
        return None
    key = headers.get("Sec-WebSocket-Key", "").strip()
    try:
        if len(base64.b64decode(key, validate=True)) != 16:
            return None
    except (binascii.Error, ValueError):
        return None
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


def mask(data: bytes, key: bytes) -> bytes:
    """XOR с ключом из 4 байт — одним большим целым, без цикла по байтам."""
    n = len(data)
    if not n:
        return b""
    k = (key * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "big") ^ int.from_bytes(k, "big")).to_bytes(n, "big")


def encode(op: int, payload: bytes = b"", fin: bool = True, key: bytes | None = None) -> bytes:
    """Кадр: сервер — без маски; ``key`` — маска клиента (для проверок)."""
    n = len(payload)
    head = bytes([(0x80 if fin else 0) | op])
    bit = 0x80 if key else 0
    if n < 126:
        head += bytes([bit | n])
    elif n < 1 << 16:
        head += bytes([bit | 126]) + struct.pack(">H", n)
    else:
        head += bytes([bit | 127]) + struct.pack(">Q", n)
    return head + (key + mask(payload, key) if key else payload)


def _read(rfile, n: int) -> bytes:
    data = rfile.read(n) if n else b""
    if len(data) < n:
        raise Closed(1006, "обрыв соединения")
    return data


def read_frame(rfile, limit: int = MAX_MESSAGE, client: bool = True) -> tuple[bool, int, bytes]:
    """Один кадр: (fin, код, данные без маски). ``client`` — кадр от клиента (обязан быть с маской); False — от
    сервера (без маски; так читают проверки)."""
    b0, b1 = _read(rfile, 2)
    fin, op, masked, n = bool(b0 & 0x80), b0 & 0x0F, bool(b1 & 0x80), b1 & 0x7F
    if b0 & 0x70:
        raise ProtocolError("биты RSV без расширений")
    if op not in (CONT, TEXT, BINARY, CLOSE, PING, PONG):
        raise ProtocolError(f"неизвестный код кадра {op}")
    if masked != client:
        raise ProtocolError("кадр клиента без маски" if client else "кадр сервера с маской")
    if op >= CLOSE and (n > 125 or not fin):
        raise ProtocolError("управляющий кадр длиннее 125 байт или разбит")
    if n == 126:
        n = struct.unpack(">H", _read(rfile, 2))[0]
    elif n == 127:
        n = struct.unpack(">Q", _read(rfile, 8))[0]
    if n > limit:
        raise ProtocolError("слишком большое сообщение", 1009)
    if not client:
        return fin, op, _read(rfile, n)
    key = _read(rfile, 4)
    return fin, op, mask(_read(rfile, n), key)


class Conn:
    """Соединение после рукопожатия: ``recv()`` → (TEXT, str) | (BINARY, bytes); ``send_*`` — из любого потока."""

    def __init__(self, rfile, wfile, limit: int = MAX_MESSAGE):
        self.rfile, self.wfile, self.limit = rfile, wfile, limit
        self.lock = threading.Lock()
        self.closed = False

    def _send(self, op: int, payload: bytes) -> None:
        with self.lock:
            if self.closed and op != CLOSE:
                raise Closed(1006, "соединение уже закрыто")
            self.wfile.write(encode(op, payload))
            self.wfile.flush()

    def send_text(self, text: str) -> None:
        self._send(TEXT, text.encode())

    def send_binary(self, data: bytes) -> None:
        self._send(BINARY, data)

    def close(self, code: int = 1000, reason: str = "") -> None:
        if self.closed:
            return
        try:
            self._send(CLOSE, struct.pack(">H", code) + reason.encode()[:120])
        except OSError:
            pass
        self.closed = True

    def recv(self) -> tuple[int, str | bytes]:
        op0, parts, size = None, [], 0
        while True:
            fin, op, data = read_frame(self.rfile, self.limit)
            if op == PING:
                self._send(PONG, data)
                continue
            if op == PONG:
                continue
            if op == CLOSE:
                code = struct.unpack(">H", data[:2])[0] if len(data) >= 2 else 1005
                self.close(1000 if code == 1005 else code)
                raise Closed(code, data[2:].decode(errors="replace"))
            if op == CONT:
                if op0 is None:
                    raise ProtocolError("продолжение без начала сообщения")
            elif op0 is not None:
                raise ProtocolError("новое сообщение посреди разбитого")
            else:
                op0 = op
            parts.append(data)
            size += len(data)
            if size > self.limit:
                raise ProtocolError("слишком большое сообщение", 1009)
            if fin:
                msg = b"".join(parts)
                if op0 == TEXT:
                    try:
                        return TEXT, msg.decode()
                    except UnicodeDecodeError:
                        raise ProtocolError("текст не в UTF-8", 1007) from None
                return BINARY, msg
