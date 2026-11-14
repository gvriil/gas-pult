"""Голос пульта: синтез (Piper, Silero) и распознавание (служба T-one ``gas_pult.asr``, запасной — faster-whisper).

Тяжёлые библиотеки грузятся только в отдельном процессе ``python -m gas_pult.voice`` или в службе
``gas-pult-asr`` — бот остаётся лёгким, а сбой синтеза не роняет пульт.
"""

from __future__ import annotations

import fcntl
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from gas_pult import asr, providers
from gas_pult.voice.catalog import PREVIEW

_preview_lock = threading.Lock()          # одно превью синтезируется за раз — без двойной работы при двойном нажатии


# ---------- тёплая служба озвучки (voice/service.py, #190) ----------
SERVICE_WAIT = 20.0          # с: подождать, пока поднимется служба (первый запуск — импорт torch и модель)


def _connect(path: Path, timeout: float) -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(path))
    except OSError:
        s.close()
        raise
    return s


def service_up(data: Path | None = None) -> bool:
    from gas_pult.voice import service
    try:
        _connect(service.socket_path(data), 1.0).close()
        return True
    except OSError:
        return False


def ensure_service(data: Path | None = None, wait: float = SERVICE_WAIT) -> bool:
    """Служба озвучки отвечает; нет — поднять её (одну на всех: замок файла) и подождать. Не вышло — False."""
    from gas_pult.voice import service
    if service_up(data):
        return True
    d = service.home(data)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(d / "start.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)                # бот и панель стартуют её одновременно — поднимет один
        if not service_up(data):
            cmd = [sys.executable, "-m", "gas_pult.voice.service", "--socket", str(service.socket_path(data))]
            with open(d / "service.log", "ab") as log:
                subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                                 env={**os.environ, "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS", "4")})
        end = time.monotonic() + wait
        while time.monotonic() < end:
            if service_up(data):
                return True
            time.sleep(0.1)
    return False


def stream(voice: str, text: str, data: Path | None = None, timeout: float = 60.0):
    """Озвучка по кускам из тёплой службы: генератор (частота, PCM 16 бит моно). Службы нет — ``asr.Unavailable``."""
    from gas_pult.voice import service
    if not ensure_service(data):
        raise asr.Unavailable("служба озвучки не поднялась")
    try:
        s = _connect(service.socket_path(data), timeout)
    except OSError as e:
        raise asr.Unavailable(f"служба озвучки: {e}") from None
    try:
        asr.send_json(s, {"op": "say", "voice": voice, "text": text})
        rate = None
        while True:
            r = asr.recv(s)
            if r is None:
                raise asr.Unavailable("служба озвучки закрыла соединение")
            kind, obj = r
            if kind == b"J":
                if "error" in obj:
                    raise RuntimeError(obj["error"])
                if "rate" in obj:
                    rate = int(obj["rate"])
                if obj.get("done"):
                    return
            elif rate:
                yield rate, obj
    except (OSError, ValueError) as e:
        raise asr.Unavailable(f"служба озвучки: {e}") from None
    finally:
        s.close()


def warm(voice: str, data: Path | None = None):
    """Загрузить модель заранее (человек открыл сессию — скоро нажмёт «Прослушать»). В фоне, без ошибок."""
    def go():
        from gas_pult.voice import service
        try:
            if ensure_service(data):
                s = _connect(service.socket_path(data), 60)
                asr.send_json(s, {"op": "warm", "voice": voice})
                asr.recv(s)
                s.close()
        except (OSError, ValueError, asr.Unavailable):
            pass
    threading.Thread(target=go, daemon=True).start()


def encode(parts, out: Path, timeout: float = 300):
    """Куски PCM → файл ``out`` (.mp3 / .ogg) одним ffmpeg: кодирование идёт, пока синтезируются следующие куски."""
    from gas_pult.voice.__main__ import ffmpeg
    it = iter(parts)
    first = next(it, None)
    if first is None:
        raise RuntimeError("нечего произносить")
    rate, pcm = first
    codec = ["-c:a", "libmp3lame", "-b:a", "64k"] if out.suffix == ".mp3" else ["-c:a", "libopus", "-b:a", "32k"]
    p = subprocess.Popen([ffmpeg(), "-loglevel", "error", "-y", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "-",
                          *codec, str(out)], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        p.stdin.write(pcm)
        for _, pcm in it:
            p.stdin.write(pcm)
        p.stdin.close()
        if p.wait(timeout) != 0:
            raise RuntimeError("кодирование звука не удалось: " + p.stderr.read().decode(errors="replace")[-200:])
    finally:
        if p.poll() is None:
            p.kill()


def synth(voice: str, text: str, out: Path, timeout: int = 300, data: Path | None = None):
    """Текст → звуковой файл. Тёплая служба (модель уже в памяти); нет её — отдельный процесс, как раньше."""
    try:
        return encode(stream(voice, text, data, timeout=timeout), out, timeout)
    except asr.Unavailable as e:
        print(f"озвучка: {e} — отдельным процессом", file=sys.stderr, flush=True)
    return synth_cold(voice, text, out, timeout)


def synth_cold(voice: str, text: str, out: Path, timeout: int = 300):
    src = out.with_suffix(".txt")
    src.write_text(text, encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, "-m", "gas_pult.voice", "tts", voice, str(src), str(out)],
                           capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError((r.stderr.strip().splitlines() or ["синтез не удался"])[-1])
    finally:
        src.unlink(missing_ok=True)


def transcribe(path: Path, model: str = "small", timeout: int = 300) -> str:
    r = subprocess.run([sys.executable, "-m", "gas_pult.voice", "stt", str(path), model],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr.strip().splitlines() or ["распознавание не удалось"])[-1])
    return r.stdout.strip()


def transcribe_any(path: Path, model: str = "small", timeout: int = 300, data: Path | None = None) -> str:
    """Голосовое → текст: служба T-one (задача 46), если запущена, — за доли секунды; нет её или сбой — whisper,
    как раньше. ``data`` — папка данных пульта (там сокет службы)."""
    try:
        return asr.transcribe(path, data, timeout=min(timeout, 120))
    except asr.Unavailable as e:
        if asr.socket_path(data).exists():             # служба есть, но не справилась — видно в журнале
            print(f"распознавание T-one: {e} — запасной путь (whisper)", file=sys.stderr, flush=True)
    return transcribe(path, model, timeout)


def preview(cache: Path, name: str, ext: str = "mp3", el: tuple[str, str] | None = None) -> bytes:
    """«Послушать»: фраза ``PREVIEW`` голосом ``name`` — из кеша ``cache/<name>.<ext>``, синтез только в первый раз.
    ``el`` — (ключ, id голоса) ElevenLabs: всегда mp3, кеш ``el-<id голоса>.mp3``, запрос в ElevenLabs — один раз."""
    if el:
        ext, stem = "mp3", "el-" + re.sub(r"[^A-Za-z0-9_-]", "_", el[1])[:64]
    else:
        stem = name
    path = cache / f"{stem}.{ext}"
    with _preview_lock:
        if path.exists() and path.stat().st_size:
            return path.read_bytes()
        cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = cache / f".{stem}-{uuid.uuid4().hex[:6]}.{ext}"
        try:
            if el:
                tmp.write_bytes(providers.el_tts(el[0], el[1], PREVIEW))
            else:
                synth(name, PREVIEW, tmp, timeout=120)
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
        return path.read_bytes()
