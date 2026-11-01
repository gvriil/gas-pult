"""Голос пульта: синтез (Piper, Silero) и распознавание (faster-whisper).

Тяжёлые библиотеки грузятся только в отдельном процессе ``python -m gas_pult.voice`` —
бот остаётся лёгким, а сбой синтеза не роняет пульт.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from gas_pult import providers
from gas_pult.voice.catalog import PREVIEW

_preview_lock = threading.Lock()          # одно превью синтезируется за раз — без двойной работы при двойном нажатии


def synth(voice: str, text: str, out: Path, timeout: int = 300):
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
