"""Whisper через faster-whisper (CTranslate2, int8, CPU): ``small`` (как сейчас в пульте) и ``large-v3-turbo``.

    ~/.local/share/asr-bench/whisper/bin/python tools/asr_bench/eng_whisper.py --model large-v3-turbo
Непотоковый: «итог после отпускания» = распознавание всего файла; псевдопоток — время окна 5/10/20 с.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c


def main() -> None:
    a = c.args(lambda p: (p.add_argument("--model", default="large-v3-turbo"),
                          p.add_argument("--beam", type=int, default=5)))
    import numpy as np
    from faster_whisper import WhisperModel

    t0 = time.perf_counter()
    model = WhisperModel(a.model, device="cpu", compute_type="int8", cpu_threads=a.threads)
    load = time.perf_counter() - t0

    def decode(pcm: bytes, sr: int) -> str:
        audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
        segs, _ = model.transcribe(audio, language="ru", beam_size=a.beam)
        return "".join(s.text for s in segs)

    out, last = {}, None
    for f in c.files(a):
        pcm, sr = c.read_wav(f)
        text, t = c.timed(decode, pcm, sr)
        out[f.stem] = c.row(text, c.duration(pcm, sr), t, final_after_end_s=round(t, 3))
        print(f.stem, out[f.stem]["rtf"], flush=True)
        last = (pcm, sr)
    window = c.window_bench(decode, *last) if last else {}
    name = "whisper-" + a.model + ("" if a.beam == 5 else f"-beam{a.beam}")
    c.save(a, name, {"model": a.model, "load_s": round(load, 2), "files": out, "window": window,
                     "streaming": False})


if __name__ == "__main__":
    main()
