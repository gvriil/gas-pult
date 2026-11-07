"""Vosk (Kaldi, alphacephei): потоковый, CPU, частичный текст на каждый кусок.

    ~/.local/share/asr-bench/vosk/bin/python tools/asr_bench/eng_vosk.py --model vosk-model-small-ru-0.22
Модель — распакованная папка в ~/.local/share/asr-bench/vosk-models/<имя> (https://alphacephei.com/vosk/models).
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c


def main() -> None:
    a = c.args(lambda p: (p.add_argument("--model", default="vosk-model-small-ru-0.22"),
                          p.add_argument("--chunk", type=float, default=0.2)))
    import vosk

    vosk.SetLogLevel(-1)
    t0 = time.perf_counter()
    model = vosk.Model(str(c.DATA / "vosk-models" / a.model))
    load = time.perf_counter() - t0

    out = {}
    for f in c.files(a):
        pcm, sr = c.read_wav(f)
        rec = vosk.KaldiRecognizer(model, sr)
        clock, final, busy = c.StreamClock(a.chunk), [], 0.0

        def step(ch: bytes, rec=rec, final=final) -> str:
            if rec.AcceptWaveform(ch):
                final.append(json.loads(rec.Result()).get("text", ""))
                return ""
            return json.loads(rec.PartialResult()).get("partial", "")

        for ch in c.chunks(pcm, sr, a.chunk):
            t1 = time.perf_counter()
            part = clock.feed_sec(len(ch) / 2 / sr, step, ch)
            busy += time.perf_counter() - t1
            clock.partial(" ".join([*final, part]))
        t1 = time.perf_counter()
        final.append(clock.finish(lambda r=rec: json.loads(r.FinalResult()).get("text", "")))
        busy += time.perf_counter() - t1
        text = " ".join(x for x in final if x)
        out[f.stem] = c.row(text, c.duration(pcm, sr), busy, **clock.result())
        print(f.stem, out[f.stem]["rtf"], clock.result(), flush=True)
    c.save(a, a.model.replace("vosk-model-", "vosk-"), {"model": a.model, "load_s": round(load, 2), "files": out,
                                                         "streaming": True, "chunk_s": a.chunk})


if __name__ == "__main__":
    main()
