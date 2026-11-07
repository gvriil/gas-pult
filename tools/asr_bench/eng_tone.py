"""T-one (T-Технологии): потоковый CTC, ONNX, CPU, 8 кГц, кусок 300 мс. Декодер — beam search + KenLM или greedy.

    ~/.local/share/asr-bench/tone/bin/python tools/asr_bench/eng_tone.py [--greedy]
Нужны файлы 8 кГц: audio/8k/<n>.wav (готовит prepare_audio.sh). Текст выдаётся фразами — по паузам в речи.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c


def main() -> None:
    a = c.args(lambda p: p.add_argument("--greedy", action="store_true"))
    import numpy as np
    import onnxruntime as ort
    from tone import BeamSearchCTCDecoder, GreedyCTCDecoder, StreamingCTCModel, StreamingCTCPipeline
    from tone.logprob_splitter import StreamingLogprobSplitter

    if not a.greedy:    # KenLM T-one — 5,4 ГБ: читаем лениво (mmap), иначе он целиком ложится в память
        import kenlm

        cfg, orig = kenlm.Config(), kenlm.Model
        cfg.load_method = kenlm.LoadMethod.LAZY
        kenlm.Model = lambda path, config=cfg: orig(path, config)

    t0 = time.perf_counter()
    so = ort.SessionOptions()
    so.intra_op_num_threads, so.inter_op_num_threads = a.threads, 1
    model = StreamingCTCModel(ort.InferenceSession(StreamingCTCModel.download_from_hugging_face(), so))
    dec = GreedyCTCDecoder() if a.greedy else BeamSearchCTCDecoder.from_hugging_face()
    pipe = StreamingCTCPipeline(model, StreamingLogprobSplitter(), dec)
    greedy = GreedyCTCDecoder()
    load = time.perf_counter() - t0
    size, pad, sr8 = pipe.CHUNK_SIZE, pipe.PADDING, StreamingCTCModel.SAMPLE_RATE

    out = {}
    for f in c.files(a):
        pcm, sr = c.read_wav(a.audio / "8k" / f.name)
        assert sr == sr8, "нужен файл 8 кГц"
        audio = np.frombuffer(pcm, np.int16).astype(np.int32)
        n = len(audio)
        # целиком (offline) — для RTF
        res, total = c.timed(pipe.forward_offline, audio)
        text = " ".join(p.text for p in res)
        # поток: кусок 300 мс приходит в реальном времени
        buf = np.pad(audio, (pad, pad))
        buf = np.pad(buf, (0, -len(buf) % size))
        parts = np.split(buf, len(buf) // size)
        clock, state, stext = c.StreamClock(size / sr8), None, []
        def step(x, s, last):
            ph, s = pipe.forward(x, s, is_last=last)
            # промежуточный текст текущей фразы — greedy по накопленным logprobs (дёшево)
            cur = greedy.forward(s[1].past_logprobs) if len(s[1].past_logprobs) else ""
            return ph, s, cur

        for i, ch in enumerate(parts):
            real = max(0, min((i + 1) * size, pad + n) - max(i * size, pad)) / sr8   # секунды настоящего звука
            ph, state, cur = clock.feed_sec(real, step, ch, state, i == len(parts) - 1)
            stext += [p.text for p in ph]
            clock.partial(" ".join([*stext, cur]))
        out[f.stem] = c.row(text, n / sr8, total, stream_text=" ".join(stext), **clock.result())
        print(f.stem, out[f.stem]["rtf"], clock.result(), flush=True)
    name = "tone-greedy" if a.greedy else "tone"
    c.save(a, name, {"model": "t-tech/T-one" + (" greedy" if a.greedy else " beam+kenlm"), "load_s": round(load, 2),
                     "files": out, "streaming": True, "chunk_s": size / sr8})


if __name__ == "__main__":
    main()
