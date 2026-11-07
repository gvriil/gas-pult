"""Голос потоком (задача 46): WebSocket на stdlib, служба распознавания с подменой движка, прокси панели, откат на
прежний путь (whisper), установка службы. Настоящая модель T-one в проверках не нужна."""

import base64
import io
import json
import os
import shutil
import socket
import struct
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import asr, voice, webapp, webauth, wsock
from gas_pult.asr import install, service
from gas_pult.config import Config

WORDS = ["покажи", "что", "изменилось", "за", "сегодня"]


# ---------- WebSocket: рукопожатие и кадры ----------

def test_accept_rfc_example():
    h = {"Upgrade": "websocket", "Connection": "keep-alive, Upgrade", "Sec-WebSocket-Version": "13",
         "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="}
    assert wsock.accept(h) == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="           # пример из RFC 6455, 1.3


@pytest.mark.parametrize("bad", [{"Upgrade": "h2c"}, {"Connection": "close"}, {"Sec-WebSocket-Version": "8"},
                                 {"Sec-WebSocket-Key": "короткий"}, {"Sec-WebSocket-Key": "YWJj"}])
def test_accept_rejects_bad_handshake(bad):
    h = {"Upgrade": "websocket", "Connection": "Upgrade", "Sec-WebSocket-Version": "13",
         "Sec-WebSocket-Key": base64.b64encode(os.urandom(16)).decode(), **bad}
    assert wsock.accept(h) is None


def test_rfc_masked_hello():
    raw = bytes([0x81, 0x85, 0x37, 0xFA, 0x21, 0x3D, 0x7F, 0x9F, 0x4D, 0x51, 0x58])   # RFC 6455, 5.7
    assert wsock.read_frame(io.BytesIO(raw)) == (True, wsock.TEXT, b"Hello")


@pytest.mark.parametrize("n", [0, 1, 125, 126, 65535, 65536, 70000])
def test_frame_lengths_roundtrip(n):
    data, key = os.urandom(n), os.urandom(4)
    raw = wsock.encode(wsock.BINARY, data, key=key)
    assert raw[1] & 0x80 and wsock.read_frame(io.BytesIO(raw)) == (True, wsock.BINARY, data)
    srv = wsock.encode(wsock.BINARY, data)                            # сервер — без маски
    assert not srv[1] & 0x80 and wsock.read_frame(io.BytesIO(srv), client=False)[2] == data


def test_mask_is_involution():
    data, key = os.urandom(1001), b"\x01\x02\x03\x04"
    assert wsock.mask(wsock.mask(data, key), key) == data and wsock.mask(b"", key) == b""
    assert wsock.mask(b"\x00\x00\x00\x00\x00", key) == b"\x01\x02\x03\x04\x01"


@pytest.mark.parametrize("raw, code", [
    (wsock.encode(wsock.TEXT, b"hi"), 1002),                              # клиент без маски
    (bytes([0xC1, 0x80]) + b"\0" * 4, 1002),                              # RSV1 без расширения
    (bytes([0x83, 0x80]) + b"\0" * 4, 1002),                              # неизвестный код
    (wsock.encode(wsock.PING, b"x" * 126, key=b"abcd"), 1002),            # управляющий длиннее 125
    (wsock.encode(wsock.PING, b"x", fin=False, key=b"abcd"), 1002),       # управляющий разбит
    (wsock.encode(wsock.BINARY, b"x" * 2000, key=b"abcd"), 1009),         # больше потолка
])
def test_protocol_errors(raw, code):
    with pytest.raises(wsock.ProtocolError) as e:
        wsock.read_frame(io.BytesIO(raw), limit=1000)
    assert e.value.code == code


def conn(*frames: bytes) -> tuple[wsock.Conn, io.BytesIO]:
    out = io.BytesIO()
    return wsock.Conn(io.BytesIO(b"".join(frames)), out, limit=1000), out


def server_frames(out: io.BytesIO) -> list[tuple[int, bytes]]:
    r, got = io.BytesIO(out.getvalue()), []
    while r.tell() < len(out.getvalue()):
        _, op, data = wsock.read_frame(r, client=False)
        got.append((op, data))
    return got


def test_fragments_ping_and_close():
    k = b"wxyz"
    c, out = conn(wsock.encode(wsock.TEXT, "При".encode(), fin=False, key=k),
                  wsock.encode(wsock.PING, b"p1", key=k),                    # пинг посреди разбитого сообщения
                  wsock.encode(wsock.CONT, "вет".encode(), key=k),
                  wsock.encode(wsock.BINARY, b"\x01\x02", key=k),
                  wsock.encode(wsock.CLOSE, struct.pack(">H", 1001) + "ухожу".encode(), key=k))
    assert c.recv() == (wsock.TEXT, "Привет")
    assert c.recv() == (wsock.BINARY, b"\x01\x02")
    with pytest.raises(wsock.Closed) as e:
        c.recv()
    assert (e.value.code, e.value.reason) == (1001, "ухожу")
    assert server_frames(out) == [(wsock.PONG, b"p1"), (wsock.CLOSE, struct.pack(">H", 1001))]   # ответный close
    with pytest.raises(wsock.Closed):
        c.send_text("после закрытия")


def test_bad_sequences():
    k = b"abcd"
    for frames, code in (([wsock.encode(wsock.CONT, b"x", key=k)], 1002),
                         ([wsock.encode(wsock.TEXT, b"a", fin=False, key=k),
                           wsock.encode(wsock.TEXT, b"b", key=k)], 1002),
                         ([wsock.encode(wsock.TEXT, b"\xff\xfe", key=k)], 1007),
                         ([wsock.encode(wsock.TEXT, b"x" * 600, fin=False, key=k),
                           wsock.encode(wsock.CONT, b"x" * 600, key=k)], 1009)):
        c, _ = conn(*frames)
        with pytest.raises(wsock.ProtocolError) as e:
            c.recv()
        assert e.value.code == code
    c, _ = conn(b"\x81")                                                     # обрыв посреди заголовка
    with pytest.raises(wsock.Closed):
        c.recv()


# ---------- служба распознавания с подменой движка ----------

class FakeStream:
    def __init__(self, rate):
        self.rate, self.n = rate, 0

    def words(self):
        return " ".join(WORDS[: self.n // self.rate])                 # слово на каждые полсекунды звука (16 бит)

    def feed(self, pcm):
        self.n += len(pcm)
        return self.words()

    def finish(self):
        return self.words() + " итог"


class FakeEngine:
    name = "fake"

    def stream(self, rate):
        if rate not in (8000, 16000):
            raise ValueError(f"частота {rate} Гц не поддерживается")
        return FakeStream(rate)


@pytest.fixture
def service_sock(monkeypatch):
    d = tempfile.mkdtemp(prefix="gp-asr-", dir="/tmp")               # unix-сокет: путь не длиннее ~104 знаков
    path = Path(d) / "asr.sock"
    srv = service.Server(path, FakeEngine(), streams=1)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv(asr.SOCKET_ENV, str(path))
    yield path
    srv.shutdown()
    srv.server_close()
    shutil.rmtree(d, ignore_errors=True)


def test_service_stream_partials_and_final(service_sock):
    assert asr.status()["engine"] == "fake" and service_sock.stat().st_mode & 0o077 == 0
    with asr.Stream(16000) as st:
        for _ in range(4):
            st.audio(b"\0" * 16000)                                   # по полсекунды
        st.end()
        evs = list(st.events(5))
    assert [e["partial"] for e in evs[:-1]] == ["покажи", "покажи что", "покажи что изменилось",
                                               "покажи что изменилось за"]
    assert evs[-1]["final"] == "покажи что изменилось за итог" and "lag_ms" in evs[-1]


def test_service_whole_file_and_limits(service_sock):
    assert asr.transcribe_pcm(b"\0" * 8000 * 2 * 2, rate=8000) == "покажи что изменилось за итог"
    with asr.Stream(16000), pytest.raises(asr.Unavailable, match="занята"):     # потолок — одно распознавание
        asr.Stream(16000)
    with pytest.raises(ValueError):
        asr.Stream(44100)                                              # такую частоту клиент не шлёт
    with socket.socket(socket.AF_UNIX) as s:                           # мусор — служба просто закрывает
        s.connect(str(service_sock))
        s.sendall(b"X\0\0\0\1z")
        try:
            assert s.recv(10) == b""
        except ConnectionResetError:
            pass
    for _ in range(50):                                                # поток освобождается чуть позже закрытия
        if asr.status()["streams"] == 0:
            break
        time.sleep(0.02)
    assert asr.status()["streams"] == 0


def test_service_absent(monkeypatch, tmp_path):
    monkeypatch.setenv(asr.SOCKET_ENV, str(tmp_path / "нет.sock"))
    assert asr.status() is None
    with pytest.raises(asr.Unavailable, match="не запущена"):
        asr.Stream(16000)
    with pytest.raises(asr.Unavailable):
        asr.transcribe(b"ogg")


# ---------- откат на прежний путь ----------

def test_transcribe_any_prefers_service_then_whisper(service_sock, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(voice, "transcribe", lambda p, m="small", timeout=300: calls.append(p) or "whisper")
    monkeypatch.setattr(asr, "decode", lambda src, rate=16000, timeout=60: b"\0" * rate * 2)
    f = tmp_path / "v.ogg"
    f.write_bytes(b"ogg")
    assert voice.transcribe_any(f) == "покажи что итог" and not calls          # служба есть — whisper не нужен

    def broken(src, rate=16000, timeout=60):
        raise asr.Unavailable("ffmpeg не разобрал запись")
    monkeypatch.setattr(asr, "decode", broken)
    assert voice.transcribe_any(f) == "whisper" and calls == [f]               # сбой — прежний путь
    monkeypatch.setenv(asr.SOCKET_ENV, str(tmp_path / "нет.sock"))
    assert voice.transcribe_any(f) == "whisper"                                 # службы нет — тоже


def test_panel_stt_uses_service_and_falls_back(service_sock, monkeypatch):
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    whisper = []
    monkeypatch.setattr(voice, "transcribe", lambda path, m="small", timeout=300: whisper.append(1) or "Привет")
    monkeypatch.setattr(asr, "decode", lambda src, rate=16000, timeout=60: b"\0" * rate * 2)
    assert p.stt(b"webm", "audio/webm") == "покажи что итог" and not whisper
    monkeypatch.setenv(asr.SOCKET_ENV, "/nonexistent/asr.sock")
    assert p.stt(b"webm", "audio/webm") == "Привет" and whisper == [1]
    assert not list((p.cfg.data / "inbox").glob("web-*"))                      # голос не храним


# ---------- прокси панели: /api/stt/stream ----------

@pytest.fixture
def panel_srv():
    panel = webapp.Panel(Config(token="1:T", owners=[1]))
    panel.people.add(2, "viewer")
    for uid in (1, 2):
        panel.people.accept(uid)
        panel.people.set_country(uid, chosen="NL")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(panel))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield panel, srv.server_address[1]
    srv.shutdown()


class Client:
    """Клиент WebSocket для проверок: рукопожатие, кадры с маской, чтение ответов."""

    def __init__(self, port, cookie="", origin=None, headers=None):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        h = {"Host": f"127.0.0.1:{port}", "Upgrade": "websocket", "Connection": "Upgrade",
             "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": key,
             **({"Origin": origin} if origin else {}), **({"Cookie": cookie} if cookie else {}), **(headers or {})}
        req = "GET /api/stt/stream HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in h.items()) + "\r\n"
        self.s.sendall(req.encode())
        self.r = self.s.makefile("rb")
        self.status = self.r.readline().decode()
        self.head = {}
        while (line := self.r.readline().decode().strip()):
            k, _, v = line.partition(":")
            self.head[k.strip().lower()] = v.strip()
        self.key = key

    def send(self, obj=None, audio=None):
        op, data = (wsock.BINARY, audio) if audio is not None else (wsock.TEXT, json.dumps(obj).encode())
        self.s.sendall(wsock.encode(op, data, key=os.urandom(4)))

    def recv(self):
        _, op, data = wsock.read_frame(self.r, client=False)
        return (op, struct.unpack(">H", data[:2])[0]) if op == wsock.CLOSE else json.loads(data)

    def close(self):
        self.s.close()


def cookie(panel, uid=1):
    return f"{webauth.COOKIE}={panel.auth.issue(uid)}"


def test_ws_stream_through_panel(panel_srv, service_sock):
    panel, port = panel_srv
    c = Client(port, cookie(panel), origin=f"http://127.0.0.1:{port}")
    assert c.status.startswith("HTTP/1.1 101") and c.head["upgrade"] == "websocket"
    assert c.head["sec-websocket-accept"] == wsock.accept({"Upgrade": "websocket", "Connection": "Upgrade",
                                                           "Sec-WebSocket-Version": "13",
                                                           "Sec-WebSocket-Key": c.key})
    c.send({"init": "", "focus": False, "rate": 16000})
    assert c.recv() == {"ready": True}
    c.send(audio=b"\0" * 16000)
    assert c.recv() == {"partial": "покажи"}
    c.send(audio=b"\0" * 16000)
    assert c.recv() == {"partial": "покажи что"}
    c.send({"end": True})
    fin = c.recv()
    assert fin["final"] == "покажи что итог"
    assert c.recv() == (wsock.CLOSE, 1000)
    c.close()


def test_ws_rejects(panel_srv, service_sock, monkeypatch):
    panel, port = panel_srv
    c = Client(port, cookie(panel), origin="https://evil.example")             # чужая страница с нашей cookie
    assert c.status.startswith("HTTP/1.1 403") or c.status.startswith("HTTP/1.0 403")
    c.close()
    c = Client(port, cookie(panel), headers={"Sec-WebSocket-Version": "8"})
    assert " 400 " in c.status
    c.close()
    c = Client(port)                                                           # без входа
    c.send({"init": "", "rate": 16000})
    assert c.recv()["code"] == "401" and c.recv() == (wsock.CLOSE, 4401)
    c.close()
    c = Client(port, cookie(panel, 2))                                         # наблюдатель — как /api/stt
    c.send({"init": "", "rate": 16000})
    assert c.recv()["code"] == "403" and c.recv() == (wsock.CLOSE, 4403)
    c.close()
    c = Client(port, "gp_focus=nope")                                           # погасшая фокус-ссылка
    c.send({"focus": True, "rate": 16000})
    assert c.recv()["code"] == "focus_gone"
    c.close()
    c = Client(port, cookie(panel))
    c.s.sendall(wsock.encode(wsock.TEXT, b"{}"))                               # кадр без маски — 1002
    assert c.recv() == (wsock.CLOSE, 1002)
    c.close()
    monkeypatch.setenv(asr.SOCKET_ENV, "/nonexistent/asr.sock")                # службы нет — панель уйдёт на /api/stt
    c = Client(port, cookie(panel))
    c.send({"init": "", "rate": 16000})
    assert c.recv()["code"] == "asr_off" and c.recv() == (wsock.CLOSE, 4503)
    c.close()


def test_ws_service_dies_midway(panel_srv, service_sock, monkeypatch):
    panel, port = panel_srv
    c = Client(port, cookie(panel))
    c.send({"rate": 16000})
    assert c.recv() == {"ready": True}
    def boom(self, pcm):
        raise RuntimeError("модель упала")
    monkeypatch.setattr(FakeStream, "feed", boom)                            # служба оборвала поток
    c.send(audio=b"\0" * 3200)
    assert c.recv()["code"] == "asr_off"
    c.close()


# ---------- установка службы ----------

def test_unit_has_memory_cap(tmp_path):
    t = install.unit_text(Path("/v/bin/python"), Path("/src"), Path("/d/asr.sock"), Path("/d/model.onnx"))
    assert "MemoryMax=1G" in t and "MemorySwapMax=0" in t and "Environment=PYTHONPATH=/src" in t
    assert "ExecStart=/v/bin/python -m gas_pult.asr.service --socket /d/asr.sock --model /d/model.onnx --threads 2" in t
    assert "WantedBy=default.target" in t


def test_fetch_model_checks_sha(tmp_path):
    src, dest = tmp_path / "m.onnx", tmp_path / "out" / "model.onnx"
    src.write_bytes(b"model")
    good = install.sha256(src)
    with pytest.raises(ValueError, match="контрольная сумма"):
        install.fetch_model(dest, src, digest="0" * 64)
    assert not dest.exists() and not dest.with_suffix(".part").exists()
    assert "скопирована" in install.fetch_model(dest, src, digest=good) and dest.read_bytes() == b"model"
    assert install.fetch_model(dest, None, url="http://нет", digest=good) == "модель уже на месте"   # без сети


# ---------- движок: понижение частоты без стыков (только где есть numpy) ----------

def test_resampler_chunking_is_seamless():
    np = pytest.importorskip("numpy")
    from gas_pult.asr import tone

    x = (np.sin(np.arange(16000 * 2) / 7) * 9000).astype("<i2").tobytes()
    whole, parts = tone.Stream.__new__(tone.Stream), tone.Stream.__new__(tone.Stream)
    for s in (whole, parts):
        s.factor, s.fir, s.n = 2, tone.lowpass(2), 0
        s.hist = np.zeros(len(s.fir) - 1, np.float32)
    a = whole._resample(x)
    b = np.concatenate([parts._resample(x[i:i + 3002]) for i in range(0, len(x), 3002)])
    assert len(a) == 16000 and np.array_equal(a, b)
    assert tone.greedy(np.zeros((0, 35), np.float32)) == ""


def test_e2e_stream_in_browser():
    import importlib.util
    from functools import partial
    from http.server import SimpleHTTPRequestHandler

    pytest.importorskip("playwright.sync_api")
    if not shutil.which("google-chrome") and not shutil.which("chrome"):
        pytest.skip("нет Chrome для Playwright")
    web = Path(webapp.__file__).resolve().parent / "web"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(web)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    e2e = Path(__file__).parent / "e2e" / "stt_stream_demo.py"
    spec = importlib.util.spec_from_file_location("stt_stream_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/?demo")
    finally:
        srv.shutdown()
