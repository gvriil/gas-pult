#!/usr/bin/env python3
"""Замер голоса пульта «до/после» (#190): сколько ждёт человек на каждом пути.

Пути и что меряем (секунды, медиана из ``--runs`` прогонов):
- stt-service — голосовое → текст через тёплую службу T-one (бот, панель, Mini App — ``voice.transcribe_any``);
- stt-whisper — запасной путь faster-whisper (когда службы нет или она упала);
- tts-<голос>-short / -long — текст → готовый звук (``voice.synth``): короткая фраза и ответ ~1000 знаков;
- tts-<голос>-first-sound — начало ответа (``webapp.head_of``): с #190 панель играет его сразу, пока готовится весь
  ответ, — это и есть ожидание до первого звука. До #190 первый звук = весь ответ (``long``).
Первый прогон после простоя поднимает службу озвучки (холодный старт) — он входит в медиану; ``--warm`` прогревает
службу до замера.

Голосовые для распознавания делает сам: озвучивает фразы Piper (5 с и ~60 с), чтобы замер повторялся без
личных записей. Запуск — тем же Python, что у панели:

    PYTHONPATH=src ~/.local/share/gas-pult/venv/bin/python tools/voice-bench.py --runs 3
    ... --only tts --voices xenia,irina
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

SHORT = "Готово. Тесты прошли, сборку можно запускать."
LONG = (" ".join([
    "Я проверил сборку и запустил тесты: прошли пятьдесят восемь из пятидесяти восьми.",
    "Изменения в трёх файлах: обработчик сообщений, список сессий и строка статуса.",
    "Осталось два вопроса: оставить ли старый формат журнала и нужен ли перезапуск службы после выкладки.",
    "Если согласны, я сделаю пулл-реквест, дождусь проверки и солью его в основную ветку.",
]) + " ") * 3
SPEECH_5 = "Привет. Открой сессию штаба и запусти тесты."
SPEECH_60 = " ".join([SPEECH_5, LONG, LONG[:300]])


def med(xs: list[float]) -> float:
    return round(statistics.median(xs), 2) if xs else float("nan")


def timed(fn, runs: int) -> tuple[float, object]:
    out, ts = None, []
    for _ in range(runs):
        t0 = time.perf_counter()
        out = fn()
        ts.append(time.perf_counter() - t0)
    return med(ts), out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--only", choices=["stt", "tts", "all"], default="all")
    ap.add_argument("--voices", default="xenia,irina", help="голоса озвучки через запятую")
    ap.add_argument("--json", help="куда записать итог (JSON)")
    ap.add_argument("--warm", action="store_true", help="прогреть службу озвучки до замера")
    a = ap.parse_args(argv)
    from gas_pult import asr, voice
    from gas_pult.voice import catalog

    res: dict[str, object] = {"when": time.strftime("%Y-%m-%d %H:%M"), "runs": a.runs}
    tmp = Path(tempfile.mkdtemp(prefix="voice-bench-"))
    try:
        if a.only in ("tts", "all"):
            if a.warm:
                for v in [x for x in a.voices.split(",") if x]:
                    try:
                        voice.synth(v, "Привет.", tmp / "warm.mp3")
                    except Exception as e:
                        print("прогрев:", e, file=sys.stderr)
            for v in [x for x in a.voices.split(",") if x]:
                if v not in catalog.installed(True):
                    res[f"tts-{v}"] = "не установлен"
                    continue
                head = LONG[:1000]
                try:
                    from gas_pult.webapp import head_of  # «первый звук» панели: начало ответа (#190)
                    head = head_of(LONG[:1000])
                except ImportError:
                    pass
                for tag, text in (("short", SHORT), ("long", LONG[:1000]), ("first-sound", head)):
                    out = tmp / f"{v}-{tag}.mp3"
                    t, _ = timed(lambda v=v, text=text, out=out: voice.synth(v, text, out), a.runs)
                    res[f"tts-{v}-{tag}"] = t
        if a.only in ("stt", "all"):
            piper = next((v for v in catalog.installed(False) if v in catalog.PIPER), None)
            if not piper:
                res["stt"] = "нет голоса Piper для тестовых голосовых"
            else:
                for tag, text in (("5s", SPEECH_5), ("60s", SPEECH_60)):
                    ogg = tmp / f"speech-{tag}.ogg"
                    voice.synth(piper, text, ogg)
                    if asr.socket_path().exists():
                        t, txt = timed(lambda ogg=ogg: asr.transcribe(ogg, None, timeout=120), a.runs)
                        res[f"stt-service-{tag}"] = t
                        res[f"stt-service-{tag}-text"] = str(txt)[:80]
                    else:
                        res[f"stt-service-{tag}"] = "служба не запущена"
                    t, txt = timed(lambda ogg=ogg: voice.transcribe(ogg, "small"), 1 if tag == "60s" else a.runs)
                    res[f"stt-whisper-{tag}"] = t
                    res[f"stt-whisper-{tag}-text"] = str(txt)[:80]
    finally:
        for f in tmp.glob("*"):
            f.unlink(missing_ok=True)
        tmp.rmdir()
    for k, v in res.items():
        print(f"{k:28} {v}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
