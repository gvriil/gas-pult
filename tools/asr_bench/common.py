"""Общая часть замера распознавания речи (задача 46). Только стандартная библиотека.

Каждый движок запускается своим python из отдельного venv (``~/.local/share/asr-bench/<движок>``) и импортирует
этот модуль по пути рядом со скриптом. Результат — JSON в папке результатов, по файлу на движок:
``{"engine", "model", "load_s", "threads", "files": {"01": {"dur", "text", "total_s", "rtf", ...}}, "window": {...}}``.

Задержка потоковых движков считается по модельным часам, а не по ``sleep``: кусок ``i`` «приходит» в момент
``(i + 1) * chunk``, обработка начинается не раньше прихода и не раньше конца предыдущего куска. Для одного потока
это то же самое, что подача в реальном времени, но замер идёт быстрее реального времени.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import wave
from pathlib import Path

DATA = Path(os.environ.get("ASR_BENCH_DATA", Path.home() / ".local/share/asr-bench"))
AUDIO = DATA / "audio"
RESULTS = DATA / "results"
REF = DATA / "ref"


def args(extra=None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--audio", type=Path, default=AUDIO, help="папка с 01.wav … (16 кГц, моно, 16 бит)")
    p.add_argument("--out", type=Path, default=RESULTS)
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--only", default="", help="через запятую: 01,05")
    if extra:
        extra(p)
    return p.parse_args()


def files(a: argparse.Namespace) -> list[Path]:
    fs = sorted(a.audio.glob("*.wav"))
    want = {x for x in a.only.split(",") if x}
    return [f for f in fs if not want or f.stem in want]


def read_wav(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path)) as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path}: нужен моно 16 бит")
        return w.readframes(w.getnframes()), w.getframerate()


def duration(pcm: bytes, sr: int) -> float:
    return len(pcm) / 2 / sr


def chunks(pcm: bytes, sr: int, sec: float):
    step = int(sr * sec) * 2
    for i in range(0, len(pcm), step):
        yield pcm[i:i + step]


class StreamClock:
    """Модельные часы подачи кусков в реальном времени (см. описание модуля)."""

    def __init__(self, chunk_sec: float):
        self.chunk, self.sent, self.done, self.first = chunk_sec, 0.0, 0.0, None

    def feed(self, fn, *a):
        """Обработать очередной кусок длиной ``chunk`` (последний может быть короче — передайте ``sec``)."""
        return self.feed_sec(self.chunk, fn, *a)

    def feed_sec(self, sec: float, fn, *a):
        self.sent += sec
        t0 = time.perf_counter()
        r = fn(*a)
        self.done = max(self.done, self.sent) + time.perf_counter() - t0
        return r

    def partial(self, text: str) -> None:
        if self.first is None and text.strip():
            self.first = self.done

    def finish(self, fn, *a):
        t0 = time.perf_counter()
        r = fn(*a)
        self.done = max(self.done, self.sent) + time.perf_counter() - t0
        return r

    def result(self) -> dict:
        return {"first_partial_s": None if self.first is None else round(self.first, 3),
                "final_lag_s": round(self.done - self.sent, 3)}


def timed(fn, *a):
    t0 = time.perf_counter()
    r = fn(*a)
    return r, time.perf_counter() - t0


def window_bench(decode, pcm: bytes, sr: int, sizes=(5, 10, 20), repeat: int = 3) -> dict:
    """Время распознавания окна последних N секунд — можно ли псевдопоток «перераспознавать окно раз в секунду»."""
    out = {}
    for s in sizes:
        part = pcm[-int(sr * s) * 2:]
        ts = []
        for _ in range(repeat):
            _, t = timed(decode, part, sr)
            ts.append(t)
        out[str(s)] = round(sorted(ts)[len(ts) // 2], 3)
    return out


def save(a: argparse.Namespace, engine: str, data: dict) -> Path:
    a.out.mkdir(parents=True, exist_ok=True)
    p = a.out / f"{engine}.json"
    data = {"engine": engine, "threads": a.threads, "loadavg_end": [round(x, 1) for x in os.getloadavg()], **data}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    os.chmod(p, 0o600)
    return p


def row(text: str, dur: float, total: float, **extra) -> dict:
    return {"dur": round(dur, 2), "text": text.strip(), "total_s": round(total, 3),
            "rtf": round(total / dur, 3) if dur else None, **extra}


# ---- нормализация и WER ---------------------------------------------------------------------------------------

_PUNCT = re.compile(r"[^\w\s]|_", re.UNICODE)


def norm(text: str) -> list[str]:
    """Нижний регистр, ё→е, дефис и пунктуация → пробел. Цифры оставляем как есть (их по-разному пишут движки)."""
    t = text.lower().replace("ё", "е")
    return _PUNCT.sub(" ", t).split()


def edits(ref: list[str], hyp: list[str]) -> int:
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1]


def wer(ref: str, hyp: str) -> tuple[int, int]:
    """(число правок, число слов эталона)."""
    r = norm(ref)
    return edits(r, norm(hyp)), len(r)
