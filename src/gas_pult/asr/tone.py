"""Движок T-one (Т-Технологии, Apache 2.0) для службы распознавания: ONNX, CPU, 8 кГц, кусок 300 мс.

Нужны только ``numpy`` и ``onnxruntime`` — их ставит ``gas-pult asr install`` в venv службы; ядро пульта этот модуль
не импортирует. Разбиение на фразы по паузам и жадный декодер — переложение ``tone.logprob_splitter`` и
``tone.decoder.GreedyCTCDecoder`` из github.com/voicekit-team/T-one (коммит 3c5b6c0) без их тяжёлых зависимостей
(kenlm, pyctcdecode, huggingface_hub); числа и порядок шагов те же, проверено на записях замера (задача 46).

Звук приходит 16 кГц (браузер) или 8 кГц (бот): частота понижается до 8 кГц фильтром нижних частот (окно Хэмминга)
и прореживанием — состояние фильтра живёт между кусками, поэтому стыков нет.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

LABELS = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя "    # 34 знака; 35-й выход модели — «пусто» (blank)
RATE, CHUNK, PAD, STATE = 8000, 2400, 2400, 219729
SILENCE, MIN_SILENCE, EXPAND, MAX_PHRASE = 0.9, 20, 3, 2000     # как в StreamingLogprobSplitter


def greedy(logprobs: np.ndarray) -> str:
    """Жадный CTC: самый вероятный знак в каждом кадре, без повторов и «пусто»."""
    if not len(logprobs):
        return ""
    t = logprobs.argmax(axis=-1)
    keep = np.ones(len(t), bool)
    keep[1:] = t[1:] != t[:-1]
    return "".join(LABELS[i] for i in t[keep].tolist() if i < len(LABELS)).strip()


def _phrases(is_speech: np.ndarray, last: bool):
    """Границы фраз (начало, конец) в кадрах: речь между паузами не короче MIN_SILENCE; последняя незаконченная
    фраза не отдаётся, пока не ``last``."""
    n = len(is_speech)
    sp = np.pad(is_speech, (MIN_SILENCE, MIN_SILENCE if last else 0))
    ch = np.diff(np.pad(~sp, (1, 1)).astype(np.int32))
    s_start = (ch == 1).nonzero()[0] - MIN_SILENCE
    s_end = (ch == -1).nonzero()[0] - MIN_SILENCE
    sep = (s_end - s_start) >= MIN_SILENCE
    s_start, s_end = s_start[sep], s_end[sep]
    starts, ends = s_end.tolist(), [*s_start.tolist()[1:], n]
    for i, (a, b) in enumerate(zip(starts, ends, strict=True)):
        while b - a >= MAX_PHRASE:
            yield a, a + MAX_PHRASE
            a += MAX_PHRASE
        if i < len(s_end) - 1:
            yield a, b


def lowpass(factor: int, taps_per: int = 16) -> np.ndarray:
    """КИХ-фильтр перед прореживанием в ``factor`` раз: срез чуть ниже 4 кГц."""
    n = taps_per * factor + 1
    fc = 3800 / (RATE * factor)
    m = np.arange(n) - (n - 1) / 2
    h = 2 * fc * np.sinc(2 * fc * m) * np.hamming(n)
    return (h / h.sum()).astype(np.float32)


class Engine:
    name = "t-one"

    def __init__(self, model: Path, threads: int = 2):
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.intra_op_num_threads, so.inter_op_num_threads = threads, 1
        self.sess = ort.InferenceSession(str(model), so, providers=["CPUExecutionProvider"])

    def run(self, chunk: np.ndarray, state: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        lp, st = self.sess.run(None, {"signal": chunk[None, :, None], "state": state})
        return lp[0].astype(np.float32, copy=False), st

    def stream(self, rate: int) -> Stream:
        return Stream(self, rate)


class Stream:
    """Одна запись: ``feed(pcm)`` → текущий текст (или None, если кусок 300 мс ещё не набрался), ``finish()`` → итог."""

    def __init__(self, engine: Engine, rate: int):
        if rate % RATE or not 1 <= rate // RATE <= 6:
            raise ValueError(f"частота {rate} Гц не поддерживается")
        self.engine, self.factor = engine, rate // RATE
        self.fir = lowpass(self.factor) if self.factor > 1 else None
        self.hist = np.zeros(0 if self.fir is None else len(self.fir) - 1, np.float32)
        self.n = 0                                       # сколько входных отсчётов прошло (фаза прореживания)
        self.buf = np.zeros(PAD, np.int32)               # модель учили с паузой 300 мс в начале и в конце
        self.state = np.zeros((1, STATE), np.float16)
        self.past = np.zeros((0, len(LABELS) + 1), np.float32)
        self.texts: list[str] = []

    def _resample(self, pcm: bytes) -> np.ndarray:
        x = np.frombuffer(pcm[: len(pcm) // 2 * 2], "<i2")
        if self.fir is None:
            return x.astype(np.int32)
        buf = np.concatenate((self.hist, x.astype(np.float32)))
        y = np.convolve(buf, self.fir, mode="valid")    # y[k] — отфильтрованный входной отсчёт self.n + k
        if len(self.hist):
            self.hist = buf[-len(self.hist):]
        y = y[(-self.n) % self.factor::self.factor]
        self.n += len(x)
        return np.clip(np.rint(y), -32768, 32767).astype(np.int32)

    def _step(self, chunk: np.ndarray, last: bool) -> None:
        lp, self.state = self.engine.run(chunk, self.state)
        lp = np.concatenate((self.past, lp))
        speech = np.exp(lp[:, -2:]).sum(axis=-1) <= SILENCE
        end = 0
        for a, b in _phrases(speech, last):
            self.texts.append(greedy(lp[max(0, a - EXPAND):b + EXPAND]))
            end = b
        if not np.nonzero(speech[end:])[0].size:
            end = max(end, len(lp) - EXPAND)
        self.past = lp[end:]

    def text(self) -> str:
        return " ".join(t for t in (*self.texts, greedy(self.past)) if t)

    def feed(self, pcm: bytes) -> str | None:
        self.buf = np.concatenate((self.buf, self._resample(pcm)))
        stepped = False
        while len(self.buf) >= CHUNK:
            chunk, self.buf = self.buf[:CHUNK], self.buf[CHUNK:]
            self._step(chunk, False)
            stepped = True
        return self.text() if stepped else None

    def finish(self) -> str:
        buf = np.concatenate((self.buf, np.zeros(PAD, np.int32)))
        buf = np.pad(buf, (0, -len(buf) % CHUNK))
        parts = np.split(buf, len(buf) // CHUNK)
        for i, ch in enumerate(parts):
            self._step(ch, i == len(parts) - 1)
        self.buf = np.zeros(0, np.int32)
        return " ".join(t for t in self.texts if t)
