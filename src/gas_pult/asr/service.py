"""Служба распознавания речи ``gas-pult-asr`` (задача 46): T-one в памяти, unix-сокет, протокол — ``gas_pult.asr``.

    python -m gas_pult.asr.service [--socket …] [--model …/model.onnx] [--threads 2] [--streams 3]

Запускается из своего venv (``gas-pult asr install``: onnxruntime, numpy) юнитом systemd --user с потолком памяти.
Здесь — только стандартная библиотека: движок (``gas_pult.asr.tone``) грузится при старте, а в проверках подменяется.
Каждое соединение — свой поток; одновременно не больше ``--streams`` распознаваний, лишнему — ``busy``.
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path

from gas_pult import asr

IDLE = 30.0                     # тишина в соединении дольше — закрываем
MAX_AUDIO_S = 600               # одна запись — не длиннее 10 минут


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, path: Path, engine, streams: int = 3):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.unlink(missing_ok=True)                # сокет прошлого запуска
        self.engine, self.limit = engine, threading.BoundedSemaphore(streams)
        self.active, self.started, self.lock = 0, time.time(), threading.Lock()
        old = os.umask(0o077)                        # сокет — только владельцу
        try:
            super().__init__(str(path), Handler)
        finally:
            os.umask(old)


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        srv: Server = self.server
        sock: socket.socket = self.request
        sock.settimeout(IDLE)
        try:
            r = asr.recv(sock)
            if not r or r[0] != b"J":
                return
            op = r[1].get("op")
            if op == "ping":
                return asr.send_json(sock, {"ok": True, "engine": getattr(srv.engine, "name", "?"),
                                            "streams": srv.active, "uptime": round(time.time() - srv.started)})
            if op != "start":
                return asr.send_json(sock, {"error": "неизвестная команда"})
            if not srv.limit.acquire(blocking=False):
                return asr.send_json(sock, {"error": "служба распознавания занята", "code": "busy"})
            try:
                with srv.lock:
                    srv.active += 1
                self.stream(sock, r[1])
            except (OSError, ValueError):
                raise
            except Exception as e:                    # сбой движка — сказать клиенту, служба живёт дальше
                print(f"gas-pult-asr: сбой распознавания: {e!r}", file=sys.stderr, flush=True)
                asr.send_json(sock, {"error": "сбой распознавания", "code": "asr_off"})
            finally:
                with srv.lock:
                    srv.active -= 1
                srv.limit.release()
        except (OSError, ValueError):
            return                                    # клиент ушёл или прислал мусор — просто закрываем

    def stream(self, sock: socket.socket, start: dict):
        srv: Server = self.server
        rate, partials = int(start.get("rate") or 16000), start.get("partials", True) is not False
        try:
            st = srv.engine.stream(rate)
        except ValueError as e:
            return asr.send_json(sock, {"error": str(e)})
        asr.send_json(sock, {"ready": True})
        last, got, cap = "", 0, MAX_AUDIO_S * rate * 2
        while True:
            r = asr.recv(sock)
            if r is None:
                return                                    # клиент ушёл, не дожидаясь итога
            kind, msg = r
            if kind == b"A":
                got += len(msg)
                if got > cap:
                    return asr.send_json(sock, {"error": f"запись длиннее {MAX_AUDIO_S // 60} минут"})
                text = st.feed(msg)
                if partials and text is not None and text != last:
                    last = text
                    asr.send_json(sock, {"partial": text})
            elif msg.get("op") == "end":
                t0 = time.perf_counter()
                final = st.finish()
                return asr.send_json(sock, {"final": final, "lag_ms": round((time.perf_counter() - t0) * 1000)})
            elif msg.get("op") == "cancel":
                return


def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(prog="gas-pult-asr", description="служба распознавания речи gas-pult (T-one)")
    p.add_argument("--socket", type=Path, default=None, help="unix-сокет (по умолчанию <данные пульта>/asr/asr.sock)")
    p.add_argument("--model", type=Path, default=asr.home() / "model" / "model.onnx")
    p.add_argument("--threads", type=int, default=2, help="потоков onnxruntime на одно распознавание")
    p.add_argument("--streams", type=int, default=3, help="одновременных распознаваний")
    a = p.parse_args(argv)
    from gas_pult.asr import tone  # numpy и onnxruntime — только в venv службы

    t0 = time.perf_counter()
    engine = tone.Engine(a.model, threads=a.threads)
    path = a.socket or asr.socket_path()
    srv = Server(path, engine, a.streams)
    print(f"gas-pult-asr: T-one загружен за {time.perf_counter() - t0:.1f} с, сокет {path}", file=sys.stderr,
          flush=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # остановка службы — убрать сокет за собой
    try:
        srv.serve_forever()
    finally:
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
