"""Тёплая служба озвучки (#190): модели Silero и Piper грузятся один раз, звук отдаётся по предложениям.

Было: каждая озвучка — новый процесс Python, импорт torch (~1,8 с) и загрузка модели (~1,6 с), потом синтез всего
текста целиком: человек ждал 5–9 с до первого звука. Тёплая модель озвучивает предложение за 0,1–0,2 с.

Запуск — по требованию (``voice.ensure_service``) или руками::

    python -m gas_pult.voice.service [--idle 1200]

Сокет ``<данные пульта>/tts/tts.sock`` (папка 0700). Нет запросов ``idle`` секунд — служба выходит и освобождает
память (на сервере мало памяти и занята подкачка); следующий запрос поднимет её снова.

Протокол — кадры, как у службы распознавания (``gas_pult.asr``): ``J`` — JSON, ``A`` — PCM 16 бит моно.
``{"op": "say", "voice": "xenia", "text": "…"}`` → ``{"rate": 48000}``, затем кадры ``A`` по предложениям,
в конце ``{"done": true}`` (или ``{"error": "…"}``). ``{"op": "warm", "voice": …}`` — загрузить модель заранее →
``{"ok": true}``. ``{"op": "ping"}`` → ``{"ok": true, "loaded": […]}``.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import sys
import threading
import time
import warnings
from pathlib import Path

from gas_pult import asr, config
from gas_pult.voice import catalog
from gas_pult.voice.text import chunks

SILERO_RATE = 48000
PIECE = 250                 # предложения склеиваются в куски не длиннее — первый звук после первого куска
IDLE = 1200                 # с без запросов — выход
FRAME = 64000               # PCM уходит кадрами не больше (лимит кадра протокола — 1 МБ)


def home(data: Path | None = None) -> Path:
    return (data or config.data_dir()) / "tts"


def socket_path(data: Path | None = None) -> Path:
    return Path(os.environ.get("GAS_PULT_TTS_SOCKET") or home(data) / "tts.sock")


class Engines:
    """Загруженные модели: Silero (одна на все голоса) и Piper (по голосу). Синтез — по одному за раз."""

    def __init__(self):
        self.lock = threading.Lock()
        self.silero = None
        self.piper: dict[str, object] = {}

    def loaded(self) -> list[str]:
        return (["silero"] if self.silero is not None else []) + sorted(self.piper)

    def warm(self, voice: str):
        if voice in catalog.SILERO and self.silero is None:
            import torch
            warnings.filterwarnings("ignore")
            torch.set_num_threads(min(4, os.cpu_count() or 4))
            self.silero = torch.package.PackageImporter(str(catalog.silero_model())).load_pickle("tts_models", "model")
            self.silero.apply_tts(text="Привет.", speaker=voice, sample_rate=SILERO_RATE)   # первый вызов — медленный
        elif voice in catalog.PIPER and voice not in self.piper:
            from piper import PiperVoice
            self.piper[voice] = PiperVoice.load(str(catalog.piper_model(voice)))
        elif voice not in catalog.SILERO and voice not in catalog.PIPER:
            raise ValueError(f"неизвестный голос: {voice}")

    def say(self, voice: str, text: str):
        """(частота, кусок PCM) по кускам текста — генератор."""
        self.warm(voice)
        if voice in catalog.SILERO:
            import numpy as np
            pause = np.zeros(int(SILERO_RATE * 0.25), np.float32)
            for piece in chunks(text, PIECE):
                if not re.search(r"\w", piece):
                    continue
                try:
                    a = self.silero.apply_tts(text=piece, speaker=voice, sample_rate=SILERO_RATE, put_accent=True,
                                              put_yo=True).numpy()
                except Exception as e:      # фраза без русских букв и т.п. — пропускаем, ответ не роняем
                    print("silero:", e, file=sys.stderr, flush=True)
                    continue
                pcm = (np.clip(np.concatenate([a, pause]), -1, 1) * 32767).astype(np.int16).tobytes()
                yield SILERO_RATE, pcm
        else:
            for c in self.piper[voice].synthesize(text):
                yield c.sample_rate, c.audio_int16_bytes


def handle(conn: socket.socket, eng: Engines):
    conn.settimeout(30)
    try:
        r = asr.recv(conn)
        if not r or r[0] != b"J":
            return
        req = r[1]
        op = req.get("op")
        if op == "ping":
            return asr.send_json(conn, {"ok": True, "loaded": eng.loaded(), "pid": os.getpid()})
        voice, text = str(req.get("voice") or ""), str(req.get("text") or "")
        with eng.lock:
            if op == "warm":
                eng.warm(voice)
                return asr.send_json(conn, {"ok": True})
            if op != "say" or not text.strip():
                return asr.send_json(conn, {"error": "ожидался say с текстом"})
            sent_rate = False
            for rate, pcm in eng.say(voice, text[:20000]):
                if not sent_rate:
                    asr.send_json(conn, {"rate": rate})
                    sent_rate = True
                for i in range(0, len(pcm), FRAME):
                    asr.send(conn, b"A", pcm[i:i + FRAME])
            if not sent_rate:
                return asr.send_json(conn, {"error": "нечего произносить"})
            asr.send_json(conn, {"done": True})
    except (OSError, ValueError) as e:
        try:
            asr.send_json(conn, {"error": str(e)})
        except OSError:
            pass
    except Exception as e:                          # сбой синтеза — ответ клиенту, служба живёт
        print("tts:", repr(e), file=sys.stderr, flush=True)
        try:
            asr.send_json(conn, {"error": f"синтез не удался: {e}"})
        except OSError:
            pass
    finally:
        conn.close()


def serve(path: Path, idle: float = IDLE):
    if not path.parent.exists():                    # своя папка — закрыта; чужую (/tmp у теста) не трогаем
        path.parent.mkdir(parents=True, mode=0o700)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    tmp.unlink(missing_ok=True)
    srv.bind(str(tmp))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)                           # атомарно: клиенты не увидят полуготовый сокет
    srv.listen(8)
    srv.settimeout(min(5.0, max(idle, 0.05)))
    eng, last = Engines(), time.monotonic()
    print(f"gas-pult tts: {path} · выход после {idle:.0f} с без запросов", flush=True)
    try:
        while True:
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                if time.monotonic() - last > idle and not eng.lock.locked():
                    return
                continue
            last = time.monotonic()
            threading.Thread(target=handle, args=(conn, eng), daemon=True).start()
    finally:
        path.unlink(missing_ok=True)
        srv.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="тёплая служба озвучки пульта")
    ap.add_argument("--idle", type=float, default=IDLE, help="с без запросов до выхода")
    ap.add_argument("--socket", default="", help="путь сокета (по умолчанию — в папке данных пульта)")
    a = ap.parse_args(argv)
    serve(Path(a.socket) if a.socket else socket_path(), a.idle)


if __name__ == "__main__":
    main()
