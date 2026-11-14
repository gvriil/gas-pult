"""Голос быстрее (#190): тёплая служба озвучки, звук по кускам, начало ответа сразу.

Было (замер 13.11, tools/voice-bench.py): озвучка Silero — 4,85 с на короткую фразу и 6,97 с на ответ в 1000 знаков:
каждый раз новый процесс, импорт torch и загрузка модели, звук — только целиком. Стало: модель в памяти службы,
начало ответа звучит через доли секунды, полный ответ догружается и подменяет начало на том же месте.
Здесь — без настоящих моделей: движок подменён, проверяется протокол, жизненный цикл службы и панель."""

import shutil
import threading
import time
from pathlib import Path
from typing import ClassVar

import pytest
from test_project_chats import call
from test_project_chats import server as server

from gas_pult import asr, voice, webapp
from gas_pult.voice import service

INDEX = (Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html").read_text(encoding="utf-8")


class FakeEngines:
    calls: ClassVar[list] = []

    def __init__(self):
        self.lock = threading.Lock()

    def loaded(self):
        return ["fake"]

    def warm(self, v):
        FakeEngines.calls.append(("warm", v))
        if v == "нет":
            raise ValueError("неизвестный голос: нет")

    def say(self, v, text):
        self.warm(v)                                                   # как настоящий: сначала модель
        FakeEngines.calls.append(("say", v, text))
        for piece in text.split("|"):
            yield 8000, piece.encode() * 2


@pytest.fixture
def svc(tmp_path, monkeypatch):
    sock = Path("/tmp") / f"gp-tts-{time.time_ns()}.sock"
    monkeypatch.setenv("GAS_PULT_TTS_SOCKET", str(sock))
    monkeypatch.setattr(service, "Engines", FakeEngines)
    FakeEngines.calls = []
    t = threading.Thread(target=service.serve, args=(sock, 0.6), daemon=True)
    t.start()
    for _ in range(50):
        if sock.exists():
            break
        time.sleep(0.02)
    yield sock, t
    t.join(3)


def test_stream_returns_pieces_in_order(svc):
    sock, _ = svc
    got = list(voice.stream("xenia", "раз|два|три"))
    assert got == [(8000, ("раз" * 2).encode()), (8000, ("два" * 2).encode()), (8000, ("три" * 2).encode())]
    assert FakeEngines.calls[-1] == ("say", "xenia", "раз|два|три")
    s = voice._connect(sock, 2)
    asr.send_json(s, {"op": "ping"})
    assert asr.recv(s)[1]["ok"] is True
    s.close()


def test_errors_come_back_as_errors(svc):
    with pytest.raises(RuntimeError, match="неизвестный голос"):
        list(voice.stream("нет", "текст"))
    with pytest.raises(RuntimeError, match="ожидался say"):
        list(voice.stream("xenia", "   "))


def test_idle_exit_removes_socket(svc):
    sock, t = svc
    t.join(5)                                                          # без запросов 0,6 с — служба вышла
    assert not t.is_alive() and not sock.exists()


def test_service_socket_is_private(svc):
    sock, _ = svc
    assert oct(sock.stat().st_mode & 0o777) == "0o600"


def test_synth_falls_back_to_separate_process(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "ensure_service", lambda data=None, wait=0: False)
    cold = []
    monkeypatch.setattr(voice, "synth_cold", lambda v, text, out, timeout=300: cold.append((v, text)))
    voice.synth("xenia", "привет", tmp_path / "a.mp3")
    assert cold == [("xenia", "привет")]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="нужен ffmpeg")
def test_encode_pcm_to_mp3_and_ogg(tmp_path, monkeypatch):
    import gas_pult.voice.__main__ as vm
    monkeypatch.setattr(vm, "ffmpeg", lambda: shutil.which("ffmpeg"))
    tone = bytes(16000)                                                # 0,5 с тишины, 16 кГц
    for ext in (".mp3", ".ogg"):
        out = tmp_path / f"a{ext}"
        voice.encode(iter([(16000, tone), (16000, tone)]), out)
        assert out.stat().st_size > 100
    with pytest.raises(RuntimeError):
        voice.encode(iter([]), tmp_path / "b.mp3")


def test_ensure_service_starts_one_and_waits(tmp_path, monkeypatch):
    sock = Path("/tmp") / f"gp-tts-{time.time_ns()}.sock"
    monkeypatch.setenv("GAS_PULT_TTS_SOCKET", str(sock))
    monkeypatch.setattr(service, "Engines", FakeEngines)
    started = []

    def popen(cmd, **kw):
        started.append(cmd)
        threading.Thread(target=service.serve, args=(sock, 0.5), daemon=True).start()
    monkeypatch.setattr(voice, "_spawn", popen)
    assert voice.ensure_service(tmp_path, wait=5) is True
    assert voice.ensure_service(tmp_path, wait=5) is True               # уже поднята — второй не стартуем
    assert len(started) == 1 and started[0][1:3] == ["-m", "gas_pult.voice.service"]
    monkeypatch.setattr(voice, "_spawn", lambda cmd, **kw: None)
    sock2 = Path("/tmp") / f"gp-tts-none-{time.time_ns()}.sock"
    monkeypatch.setenv("GAS_PULT_TTS_SOCKET", str(sock2))
    assert voice.ensure_service(tmp_path, wait=0.3) is False            # не поднялась — запасной путь


def test_head_of():
    t = "Готово. Тесты прошли. " + "Длинное предложение без точки " * 20
    assert webapp.head_of(t) == "Готово. Тесты прошли."
    one = "слово " * 100
    h = webapp.head_of(one)
    assert len(h) <= webapp.HEAD_CHARS and h.startswith("слово")
    assert webapp.head_of("") == ""


def test_panel_head_and_warm(server, monkeypatch):
    p, base, *_ = server
    said, warmed = [], []
    monkeypatch.setattr(p, "message", lambda w, msg: "Первое. Второе. " + "Дальше много текста. " * 40)
    monkeypatch.setattr(p, "voice", lambda personal=False: "xenia")
    monkeypatch.setattr(webapp.voice, "synth",
                        lambda v, text, out, data=None: said.append(text) or out.write_bytes(b"x"))
    monkeypatch.setattr(webapp.voice, "warm", lambda v, data=None: warmed.append(v))
    tok = p.auth.issue(1)
    import urllib.request

    from gas_pult import webauth

    def get(path):
        req = urllib.request.Request(base + path, headers={"Cookie": f"{webauth.COOKIE}={tok}"})
        with urllib.request.urlopen(req) as r:
            return r.status, r.read()
    assert get("/api/tts?w=@1&full=1&head=1") == (200, b"x")
    assert get("/api/tts?w=@1&full=1")[0] == 200
    assert len(said[0]) <= webapp.HEAD_CHARS and len(said[1]) > 500     # начало — коротко, потом весь ответ
    assert call(base, "/api/tts/warm?w=@1", tok=tok) == (200, {"ok": True, "voice": "xenia"}) and warmed == ["xenia"]


def test_ui_plays_head_first_then_swaps():
    f = INDEX[INDEX.index("async function ttsFetch"):]
    f = f[:f.index("\n}\n")]
    assert f.index('"&head=1"') < f.index("return api(url)")              # начало — первым, весь ответ — после
    assert "ttsWarm(id);" in INDEX and "/api/tts/warm" in INDEX
    assert "voice.swapping" in INDEX                                     # подмена — не «пауза» для интерфейса
