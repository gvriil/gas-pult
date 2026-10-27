"""Голос пульта: синтез (Piper, Silero) и распознавание (faster-whisper).

Тяжёлые библиотеки грузятся только в отдельном процессе ``python -m gas_pult.voice`` —
бот остаётся лёгким, а сбой синтеза не роняет пульт.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


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
