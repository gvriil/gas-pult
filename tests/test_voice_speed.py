"""Голос: «кратко» и «целиком» звучат по-разному; готовая запись распознаётся кусками параллельно; отказ ElevenLabs
запоминается — следующая запись не ждёт облако."""

import array
import math
import shutil
import tempfile
import threading
from pathlib import Path

import pytest
from websrc import web_source

from gas_pult import asr, providers, transcripts, voice, webapp
from gas_pult.asr import service
from gas_pult.config import Config

LONG = """## Итог

Сделал правку в модуле озвучки, проверил тесты. Всё зелёное, запрос на слияние открыт.

> Важно: живые службы не перезапускал.

## Подробности

| Шаг | Время |
|---|---|
| сборка | 3 с |
| тесты | 40 с |

""" + "\n\n".join(f"Абзац {i}: подробное пояснение, что изменилось и почему так лучше для работы. " * 3
                  for i in range(12))


# ---------- «кратко» ≠ «целиком» ----------

def test_brief_of_cleaned_long_answer_is_shorter():
    full = transcripts.clean(LONG)
    short = webapp.brief(full)
    assert "\n\n" not in full                       # clean схлопывает пустые строки — на этом «кратко» и ломалось
    assert short != full and len(short) < len(full) and len(short) <= 700
    assert short.startswith("Итог") and "Абзац 11" not in short


def test_brief_cuts_one_huge_paragraph_at_sentence():
    text = "Первая мысль про изменения. " * 60
    short = webapp.brief(text)
    assert len(short) <= 700 and short.endswith(".") and short != text.strip()
    words = "слово " * 300                              # без точек — по пробелу
    assert len(webapp.brief(words)) <= 700 and not webapp.brief(words).endswith(" ")


def test_brief_keeps_short_answer_whole():
    assert webapp.brief("Готово.\nВсё работает.") == "Готово.\nВсё работает."
    assert webapp.brief("") == ""


def test_tts_sends_different_text_per_mode(monkeypatch):
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    said = []
    monkeypatch.setattr(p, "message", lambda w, i: LONG)
    monkeypatch.setattr(p, "voice", lambda personal=False: "irina")
    monkeypatch.setattr(voice, "synth", lambda v, text, out, timeout=300: said.append(text) or out.write_bytes(b"mp3"))
    assert p.tts({"id": "@1"}, full=True) == b"mp3"
    p.tts({"id": "@1"}, full=False)
    full, short = said
    assert short != full and len(short) < len(full)
    assert full.startswith(short.split("\n")[0])


def test_panel_cache_key_includes_mode():
    """Плеер панели: тот же ответ в другом режиме — новый запрос (full= в адресе), ответ старого режима не играет."""
    page = web_source()
    assert "voice.msg === msg && voice.full === full" in page
    assert "voice.msg !== msg || voice.full !== full) return;" in page
    assert page.count("/api/tts?w=${encodeURIComponent(") == 2 and page.count("&full=${") == 2


# ---------- готовая запись: куски в тихих местах, параллельно ----------

def tone(seconds: float, rate: int = 16000, amp: int = 8000) -> bytes:
    return array.array("h", (int(amp * math.sin(i / rate * 2 * math.pi * 300)) for i in range(int(seconds * rate)))
                       ).tobytes()


def test_cuts_land_in_quiet_place():
    rate = 16000
    pcm = tone(11) + b"\0" * (rate * 2 // 2) + tone(9)          # пауза 0,5 с на 11-й секунде
    (cut,) = asr.cuts(pcm, rate, parts=2)
    assert 11 * rate * 2 <= cut <= 11.5 * rate * 2 and cut % 2 == 0
    assert asr.cuts(tone(10), rate, parts=2) == []                # короче 2 × PART_MIN_S — целиком
    assert asr.cuts(pcm, rate, parts=1) == []


class FakeStream:
    def __init__(self):
        self.n = 0

    def feed(self, pcm):
        self.n += len(pcm)

    def finish(self):
        return f"кусок{self.n // 32000}"                        # итог — длина куска в секундах


class FakeEngine:
    name = "fake"

    def stream(self, rate):
        return FakeStream()


@pytest.fixture
def svc(monkeypatch):
    d = tempfile.mkdtemp(prefix="gp-asr-", dir="/tmp")
    servers = []

    def start(streams):
        path = Path(d) / f"s{streams}.sock"
        srv = service.Server(path, FakeEngine(), streams=streams)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return path
    yield start
    for s in servers:
        s.shutdown()
        s.server_close()
    shutil.rmtree(d, ignore_errors=True)


def test_transcribe_pcm_parallel_keeps_order(svc):
    path = svc(3)
    pcm = tone(11) + b"\0" * 16000 + tone(9)
    assert asr.transcribe_pcm(pcm, 16000, path) == "кусок11 кусок9"      # два куска, по порядку
    assert asr.transcribe_pcm(pcm, 16000, path, parts=1) == "кусок20"     # как раньше — одним потоком


def test_transcribe_pcm_busy_service_falls_back_to_one_stream(svc):
    path = svc(1)                                                         # свободен один поток
    pcm = tone(11) + b"\0" * 16000 + tone(9)
    assert asr.transcribe_pcm(pcm, 16000, path) == "кусок20"


# ---------- ElevenLabs отказал — не ждём его снова ----------

def test_el_refusal_is_remembered(monkeypatch):
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    calls = []

    def el_stt(key, data, name):
        calls.append(1)
        raise providers.ProviderError("ElevenLabs: исчерпан лимит тарифа или слишком много запросов")
    monkeypatch.setattr(providers, "el_stt", el_stt)
    monkeypatch.setattr(providers, "load_keys", lambda: {"elevenlabs": "поддельный"})
    monkeypatch.setattr(p, "voice_settings", lambda: {"stt": "elevenlabs", "tts": "local"})
    monkeypatch.setattr(voice, "transcribe_any", lambda *a, **k: "локально")
    assert p.stt(b"webm", "audio/webm") == "локально" and calls == [1]
    assert p.stt(b"webm", "audio/webm") == "локально" and calls == [1]    # второй раз — сразу локально
    assert "исчерпан лимит" in p.fallback_note()
    p.el_pause_until = 0                                                   # пауза кончилась — снова пробуем облако
    p.stt(b"webm", "audio/webm")
    assert calls == [1, 1]
