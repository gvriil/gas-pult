"""GigaAM-v3 (Сбер): Conformer, PyTorch CPU. Варианты: v3_e2e_rnnt (с пунктуацией), v3_rnnt, v3_ctc, v3_e2e_ctc.

    ~/.local/share/asr-bench/gigaam/bin/python tools/asr_bench/eng_gigaam.py --model v3_e2e_rnnt
Непотоковый, окно модели — до 25 с. Длинные записи режем сами по самой тихой точке (без pyannote и токена HF).
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c

MAX_SEG = 20.0      # с: длиннее — режем
MIN_SEG = 10.0      # с: самая тихая точка ищется в [MIN_SEG, MAX_SEG]


def cuts(x, sr: int) -> list[tuple[int, int]]:
    """Границы кусков ≤ MAX_SEG с: разрез — в самом тихом окне 100 мс между MIN_SEG и MAX_SEG."""
    import numpy as np

    out, start, n, hop = [], 0, len(x), int(sr * 0.1)
    while n - start > MAX_SEG * sr:
        lo, hi = start + int(MIN_SEG * sr), start + int(MAX_SEG * sr)
        frames = x[lo:hi][: (hi - lo) // hop * hop].reshape(-1, hop)
        cut = lo + int(np.argmin((frames.astype(np.float32) ** 2).mean(1))) * hop + hop // 2
        out.append((start, cut))
        start = cut
    out.append((start, n))
    return out


def load_hf(name: str):
    """Веса с Hugging Face (ai-sage/GigaAM-v3, ветка = вариант) в классы пакета gigaam — без trust_remote_code.

    Нужно, когда CDN Сбера недоступен (на 07.11.2026 у него истёк сертификат).
    """
    import importlib
    import json

    import torch
    from gigaam.model import GigaAMASR
    from huggingface_hub import hf_hub_download
    from omegaconf import OmegaConf

    rev = name.removeprefix("v3_")
    get = lambda f: hf_hub_download("ai-sage/GigaAM-v3", f, revision=rev)  # noqa: E731
    cfg = json.loads(Path(get("config.json")).read_text())["cfg"]["model"]["cfg"]
    where = {m: importlib.import_module(f"gigaam.{m}") for m in ("preprocess", "encoder", "decoder", "decoding")}

    def fix(x):
        if isinstance(x, dict):
            return {k: fix(v) for k, v in x.items()}
        if isinstance(x, str) and x.startswith("modeling_gigaam."):
            cls = x.split(".", 1)[1]
            return next(f"gigaam.{m}.{cls}" for m, mod in where.items() if hasattr(mod, cls))
        return x

    cfg = fix(cfg)
    if (cfg.get("decoding") or {}).get("model_path"):
        cfg["decoding"]["model_path"] = get(cfg["decoding"]["model_path"])
    model = GigaAMASR(OmegaConf.create(cfg))
    sd = torch.load(get("pytorch_model.bin"), map_location="cpu", weights_only=True)
    model.load_state_dict({k.removeprefix("model."): v for k, v in sd.items()})
    return model


def main() -> None:
    a = c.args(lambda p: (p.add_argument("--model", default="v3_e2e_rnnt"),
                          p.add_argument("--hf", action="store_true", help="веса с Hugging Face, не с CDN Сбера")))
    import gigaam
    import numpy as np
    import torch

    torch.set_num_threads(a.threads)
    t0 = time.perf_counter()
    if a.hf:
        model = load_hf(a.model)
    else:
        model = gigaam.load_model(a.model, fp16_encoder=False, device="cpu",
                                  download_root=str(c.DATA / "gigaam-weights"))
    model.eval()
    load = time.perf_counter() - t0

    @torch.inference_mode()
    def piece(x) -> str:
        wav = torch.from_numpy(x.astype(np.float32) / 32768).unsqueeze(0)
        length = torch.full([1], wav.shape[-1])
        enc, enc_len = model.forward(wav, length)
        return model._decode(enc, enc_len, length, False)[0][0]

    def decode(pcm: bytes, sr: int) -> str:
        x = np.frombuffer(pcm, np.int16)
        return " ".join(piece(x[s:e]) for s, e in cuts(x, sr))

    out, last = {}, None
    for f in c.files(a):
        pcm, sr = c.read_wav(f)
        text, t = c.timed(decode, pcm, sr)
        out[f.stem] = c.row(text, c.duration(pcm, sr), t, final_after_end_s=round(t, 3))
        print(f.stem, out[f.stem]["rtf"], flush=True)
        last = (pcm, sr)
    window = c.window_bench(decode, *last) if last else {}
    c.save(a, "gigaam-" + a.model, {"model": "GigaAM " + a.model, "load_s": round(load, 2), "files": out,
                                    "window": window, "streaming": False})


if __name__ == "__main__":
    main()
