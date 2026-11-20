"""Потоковое распознавание речи (задача 46): клиент службы ``gas-pult-asr`` и её протокол. Только stdlib.

Служба (``python -m gas_pult.asr.service``) живёт отдельным процессом в своём venv (``gas-pult asr install``): движок
T-one (ONNX, CPU) грузится один раз и держится в памяти. Связь — unix-сокет ``<данные пульта>/asr/asr.sock`` (папка
0700), без сети.

Протокол — кадры ``[тип: 1 байт][длина: 4 байта, big-endian][данные]``: ``J`` — объект JSON (UTF-8), ``A`` — звук
PCM 16 бит little-endian моно. Клиент: ``{"op": "start", "rate": 16000, "partials": true}`` → служба:
``{"ready": true}`` (или ``{"error", "code": "busy"}``); затем кадры ``A`` — служба отвечает ``{"partial": "…"}``, когда
текст изменился; ``{"op": "end"}`` → ``{"final": "…", "lag_ms": …}``. ``{"op": "ping"}`` → ``{"ok": true, …}``.

Нет службы, занята или упала — ``Unavailable``: пульт идёт нынешним путём (облако или whisper, ``voice.transcribe``).

Служба выходит после простоя (``--idle`` в юните, аудит #189: модель держит ~0,6 ГБ). Клиент поднимает её снова сам —
``ensure_service``: ``systemctl --user start`` юнита, если он установлен и слушает этот же сокет, и ждёт сокет.
"""

from __future__ import annotations

import array
import itertools
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

from gas_pult import config

SOCKET_ENV = "GAS_PULT_ASR_SOCKET"        # другой сокет (проверка, второй пульт)
UNIT = "gas-pult-asr.service"
HDR = struct.Struct(">cI")
MAX_FRAME = 1 << 20                        # кусок звука — десятки КБ; больше 1 МБ — ошибка протокола
RATES = (8000, 16000, 48000)               # частоты, которые служба понижает до 8 кГц сама
CHUNK = 32000                              # по столько байт файл уходит в службу (1 с при 16 кГц)
PARALLEL = 2                               # готовую запись — в столько потоков службы сразу (из её 3; один — панели)
PART_MIN_S = 8.0                           # кусок готовой записи не короче, с
SEG_MAX_S = 300                            # и не длиннее, с: лимит службы — 10 минут на поток (MAX_AUDIO_S)
START_WAIT = 8.0                           # с: сколько ждать сокет после запуска службы (модель грузится 1–4 с)
QUIET_S = 0.3                              # разрез — посреди самого тихого окна такой длины, с


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


# ---------- запуск по требованию ----------

def alive(path: Path) -> bool:
    """Сокет принимает соединения (файл сокета мог остаться от упавшей службы)."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(str(path))
        return True
    except OSError:
        return False


def unit_file() -> Path:
    return Path.home() / ".config/systemd/user" / UNIT


def unit_socket() -> Path | None:
    """Сокет из ``ExecStart`` установленного юнита (``--socket …``); юнита нет — None."""
    try:
        text = unit_file().read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("ExecStart=") and "--socket" in line:
            words = line.split()
            return Path(words[words.index("--socket") + 1]) if words[-1] != "--socket" else None
    return None


def _start() -> None:
    """Запустить юнит службы, не дожидаясь его (тесты подменяют только это)."""
    subprocess.run(["systemctl", "--user", "start", "--no-block", UNIT], capture_output=True, timeout=10)


def ensure_service(data: Path | None = None, wait: float = START_WAIT) -> bool:
    """Служба отвечает; нет — поднять её юнитом systemd и подождать сокет. Юнит не установлен или слушает другой
    сокет (второй пульт, проверка) — не трогаем, False: пульт уйдёт на запасной путь."""
    path = socket_path(data)
    if alive(path):
        return True
    unit = unit_socket()
    if unit is None or unit != path:
        return False
    try:
        _start()
    except (OSError, subprocess.SubprocessError):
        return False
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if alive(path):
            return True
        time.sleep(0.1)
    return False


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


def _whole(st: Stream, pcm: bytes, timeout: float) -> str:
    """Открытый поток: вся запись → итог."""
    st.sock.settimeout(timeout)
    for i in range(0, len(pcm), CHUNK):
        st.audio(pcm[i:i + CHUNK])
    st.end()
    for ev in st.events(timeout):
        if "error" in ev:
            raise Unavailable(str(ev["error"]))
        if "final" in ev:
            return str(ev["final"]).strip()
    return ""


def cuts(pcm: bytes, rate: int = 16000, parts: int = PARALLEL) -> list[int]:
    """Где резать готовую запись на ``parts`` кусков для одновременного распознавания (смещения в байтах): самое тихое
    окно ``QUIET_S`` возле каждой равной доли (± четверть доли). Порог тишины не задаём — шум у записей разный, а
    самое тихое место между словами есть всегда. Кусок не короче ``PART_MIN_S``; коротко — пустой список."""
    n = len(pcm) // 2
    parts = min(parts, int(n / rate // PART_MIN_S))
    if parts < 2:
        return []
    x = array.array("h", pcm[: n * 2])
    if sys.byteorder == "big":
        x.byteswap()
    win, step, part = int(QUIET_S * rate), rate // 10, n // parts
    out: list[int] = []
    for k in range(1, parts):
        lo = max(k * part - part // 4, (out[-1] if out else 0) + int(PART_MIN_S * rate) - win // 2)
        hi = min(k * part + part // 4, n - int(PART_MIN_S * rate) - win // 2)
        if lo > hi:
            continue
        best = min(range(lo, hi + 1, step), key=lambda i: sum(map(abs, x[i:i + win])))
        out.append(best + win // 2)
    return [i * 2 for i in out]


BUSY_WAIT = (0.05, 0.1, 0.2, 0.4)


def _stream_wait(rate: int, path: Path | None) -> Stream:
    """Поток службы для следующего куска. Служба отдаёт ответ куска чуть раньше, чем освобождает поток, — сразу
    после своего куска работник получал «занята» и бросал очередь (20.11, нестабильный тест и та же гонка на сервере
    при одном свободном потоке). Поэтому «занята» — несколько коротких повторов, всего < 1 с."""
    for pause in (*BUSY_WAIT, None):
        try:
            return Stream(rate, partials=False, path=path)
        except Unavailable:
            if pause is None:
                raise
            time.sleep(pause)
    raise AssertionError("недостижимо")


def transcribe_pcm(pcm: bytes, rate: int = 16000, path: Path | None = None, timeout: float = 60,
                   parts: int = PARALLEL) -> str:
    """Готовая запись целиком → текст (бот, ``/api/stt``).

    Служба считает в темпе ~0,2 с на секунду записи и берёт не больше ``SEG_MAX_S``·2 звука на поток. Поэтому запись
    режем в тихих местах (``cuts``) на куски не длиннее ``SEG_MAX_S`` (кусков не меньше ``parts``) и
    распознаём их ``parts`` потоками; кусков больше, чем потоков, — по очереди. 18.11 запись длиннее 20 минут резалась
    на 2 куска больше лимита службы (10 минут) — «Broken pipe» и потеря записи (GAS-34). ``timeout`` — на кусок."""
    n = max(parts, -(-len(pcm) // (2 * rate * SEG_MAX_S)))
    edges = [0, *cuts(pcm, rate, n), len(pcm)]
    segs = [pcm[a:b] for a, b in itertools.pairwise(edges)]
    if len(segs) == 1:
        st = Stream(rate, partials=False, path=path)
        try:
            return _whole(st, pcm, timeout)
        except OSError as e:
            raise Unavailable(f"служба распознавания: {e}") from None
        finally:
            st.close()
    out: list[str | BaseException | None] = [None] * len(segs)
    todo = list(range(len(segs)))
    lock = threading.Lock()

    def worker():
        while True:
            with lock:
                if not todo:
                    return
                i = todo.pop(0)
            try:
                st = _stream_wait(rate, path)
            except Unavailable as e:
                with lock:
                    todo.insert(0, i)                 # поток службы занят — кусок вернётся другому работнику
                out[i] = e if out[i] is None else out[i]
                return
            try:
                out[i] = _whole(st, segs[i], timeout)
            except (Unavailable, OSError, ValueError) as e:
                out[i] = e
            finally:
                st.close()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(min(parts, len(segs)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout * len(segs) + 5)
    if todo:                                      # потоков не досталось ни одному оставшемуся куску
        raise Unavailable(f"служба распознавания занята: не распознано кусков {len(todo)} из {len(segs)}")
    for r in out:
        if isinstance(r, BaseException) or r is None:
            raise Unavailable(f"служба распознавания: {r}")
    return " ".join(r for r in out if r)


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
    if not ensure_service(data):              # без службы и ffmpeg не запускаем; ушла после простоя — поднимаем
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
