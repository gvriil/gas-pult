"""ElevenLabs Scribe (облако): пакетный ``/v1/speech-to-text`` (scribe_v1 — как сейчас в пульте, scribe_v2) и
потоковый WebSocket ``scribe_v2_realtime``.

    ~/.local/share/asr-bench/eleven/bin/python tools/asr_bench/eng_eleven.py --mode batch --model scribe_v2
    ~/.local/share/asr-bench/eleven/bin/python tools/asr_bench/eng_eleven.py --mode realtime
Ключ: переменная ELEVENLABS_API_KEY или поле "elevenlabs" в --key-file (по умолчанию — секреты пульта).
Потоковый режим шлёт звук в настоящем реальном времени (sleep), задержка — по настенным часам, с сетью.
Пакетный — только stdlib; потоковому нужен пакет websockets.
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c

API = "https://api.elevenlabs.io/v1/speech-to-text"
WSS = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"


def key(path: Path) -> str:
    k = os.environ.get("ELEVENLABS_API_KEY")
    if not k:
        k = json.loads(path.read_text())["elevenlabs"]
    return k


def batch(k: str, model: str, ogg: Path) -> str:
    b = uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"model_id\"\r\n\r\n{model}\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"language_code\"\r\n\r\nru\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"tag_audio_events\"\r\n\r\nfalse\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{ogg.name}\"\r\n"
            "Content-Type: audio/ogg\r\n\r\n").encode() + ogg.read_bytes() + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(API, body, {"xi-api-key": k, "Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r).get("text", "")


async def realtime(k: str, pcm: bytes, sr: int, chunk: float) -> dict:
    import asyncio

    import websockets

    url = f"{WSS}?model_id=scribe_v2_realtime&audio_format=pcm_{sr}&language_code=ru&commit_strategy=manual"
    first, final, done = None, [], asyncio.Event()
    async with websockets.connect(url, additional_headers={"xi-api-key": k}, max_size=None) as ws:
        start = time.perf_counter()

        async def reader():
            nonlocal first
            async for raw in ws:
                m = json.loads(raw)
                t = m.get("message_type")
                if t == "partial_transcript" and first is None and m.get("text", "").strip():
                    first = time.perf_counter() - start
                elif t == "committed_transcript":
                    final.append(m.get("text", ""))
                    if sent_all:
                        done.set()
                elif t not in ("session_started", "partial_transcript", "committed_transcript_with_timestamps"):
                    print("  сервер:", t, m.get("error") or m.get("warning"), flush=True)

        sent_all = False
        task = asyncio.create_task(reader())
        parts = list(c.chunks(pcm, sr, chunk))
        for i, ch in enumerate(parts):
            due = start + i * chunk
            await asyncio.sleep(max(0.0, due - time.perf_counter()))
            last = i == len(parts) - 1
            if last:
                sent_all = True
                await asyncio.sleep(max(0.0, start + (i + 1) * chunk - time.perf_counter()))
            await ws.send(json.dumps({"message_type": "input_audio_chunk", "sample_rate": sr, "commit": last,
                                      "audio_base_64": base64.b64encode(ch).decode()}))
        end = time.perf_counter()
        try:
            await asyncio.wait_for(done.wait(), 30)
        except TimeoutError:
            print("  нет итога за 30 с", flush=True)
        lag = time.perf_counter() - end
        task.cancel()
    return {"text": " ".join(final), "first_partial_s": None if first is None else round(first, 3),
            "final_lag_s": round(lag, 3)}


def main() -> None:
    a = c.args(lambda p: (p.add_argument("--mode", choices=["batch", "realtime"], default="batch"),
                          p.add_argument("--model", default="scribe_v2"),
                          p.add_argument("--chunk", type=float, default=0.25),
                          p.add_argument("--key-file", type=Path,
                                         default=Path.home() / ".config/gas-pult/secrets.json")))
    k = key(a.key_file)
    out = {}
    for f in c.files(a):
        pcm, sr = c.read_wav(f)
        dur = c.duration(pcm, sr)
        try:
            if a.mode == "batch":
                ogg = f.with_suffix(".ogg")
                text, t = c.timed(batch, k, a.model, ogg if ogg.exists() else f)
                out[f.stem] = c.row(text, dur, t, final_after_end_s=round(t, 3))
            else:
                import asyncio

                r = asyncio.run(realtime(k, pcm, sr, a.chunk))
                out[f.stem] = c.row(r.pop("text"), dur, dur + r["final_lag_s"], **r)
        except urllib.error.HTTPError as e:     # квота, ключ — записываем и идём дальше
            detail = json.loads(e.read() or b"{}").get("detail", {})
            print(f.stem, "ошибка", e.code, detail.get("code") if isinstance(detail, dict) else detail, flush=True)
            continue
        print(f.stem, {x: y for x, y in out[f.stem].items() if x != "text"}, flush=True)
    name = "eleven-" + (a.model if a.mode == "batch" else "scribe_v2_realtime")
    c.save(a, name, {"model": name, "load_s": 0, "files": out, "streaming": a.mode == "realtime", "cloud": True})


if __name__ == "__main__":
    main()
