"""Рабочий процесс голоса.

    python -m gas_pult.voice tts <голос> <текст.txt> <выход.ogg|.mp3|.wav>
    python -m gas_pult.voice stt <вход> [модель whisper]
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import warnings
import wave
from pathlib import Path

from gas_pult.voice import catalog
from gas_pult.voice.text import chunks

RATE = 48000


def ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        if exe := shutil.which("ffmpeg"):
            return exe
        raise SystemExit("нужен ffmpeg: pip install imageio-ffmpeg или системный ffmpeg") from None


def piper_wav(voice: str, src: Path, wav: Path):
    exe = Path(sys.executable).with_name("piper")
    exe = str(exe) if exe.exists() else shutil.which("piper") or "piper"
    with open(src, "rb") as f:
        subprocess.run([exe, "-m", str(catalog.piper_model(voice)), "-f", str(wav)],
                       stdin=f, check=True, stderr=subprocess.DEVNULL)


def silero_wav(voice: str, src: Path, wav: Path):
    import numpy as np
    import torch

    warnings.filterwarnings("ignore")
    torch.set_num_threads(4)
    model = torch.package.PackageImporter(str(catalog.silero_model())).load_pickle("tts_models", "model")
    pause = np.zeros(int(RATE * 0.25), np.float32)
    parts = []
    for c in chunks(src.read_text(encoding="utf-8")):
        if not re.search(r"\w", c):
            continue
        try:
            audio = model.apply_tts(text=c, speaker=voice, sample_rate=RATE, put_accent=True, put_yo=True)
            parts += [audio.numpy(), pause]
        except Exception as e:      # фраза без русских букв и т.п. — пропускаем, не роняем весь ответ
            print("silero:", e, file=sys.stderr)
    if not parts:
        raise SystemExit("silero: нечего произносить")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(np.concatenate(parts), -1, 1) * 32767).astype(np.int16).tobytes())


def tts(voice: str, src: str, out: str):
    src_p, out_p = Path(src), Path(out)
    wav = out_p if out_p.suffix == ".wav" else out_p.with_suffix(".tmp.wav")
    if voice in catalog.SILERO:
        silero_wav(voice, src_p, wav)
    elif voice in catalog.PIPER:
        piper_wav(voice, src_p, wav)
    else:
        raise SystemExit(f"неизвестный голос: {voice}")
    if wav != out_p:
        codec = ["-c:a", "libmp3lame", "-b:a", "64k"] if out_p.suffix == ".mp3" else ["-c:a", "libopus", "-b:a", "32k"]
        subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-i", str(wav), *codec, str(out_p)], check=True)
        wav.unlink()


def stt(src: str, model: str = "small"):
    # PyAV в faster-whisper капризен — декодируем сами через ffmpeg
    import numpy as np
    from faster_whisper import WhisperModel

    pcm = subprocess.run([ffmpeg(), "-loglevel", "error", "-i", src, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
    segments, _ = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=4).transcribe(audio, language="ru")
    print("".join(s.text for s in segments).strip())


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    if cmd == "tts" and len(args) == 3:
        tts(*args)
    elif cmd == "stt" and 1 <= len(args) <= 2:
        stt(*args)
    else:
        raise SystemExit(__doc__)
