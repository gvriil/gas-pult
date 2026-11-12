"""Сервер для демо-прогонов (``?demo``): статический или настоящая панель — только 127.0.0.1, гасится по выходу.

    with demo_server("static") as base: ...   # python3 -m http.server --bind 127.0.0.1 в src/gas_pult/web
    with demo_server("panel") as base: ...    # настоящий webapp.handler (focus_live.start: временные HOME, данные,
                                              # свой tmux, подставной claude) — заголовки и маршруты как в бою

``base`` — адрес вида ``http://127.0.0.1:<порт>/?demo``.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from focus_live import ROOT, free_port, start

WEB = ROOT / "src" / "gas_pult" / "web"


def wait_up(url: str, proc: subprocess.Popen, sec: float = 15) -> None:
    t = time.time() + sec
    while time.time() < t:
        if proc.poll() is not None:
            raise RuntimeError("сервер демо не запустился")
        try:
            urllib.request.urlopen(url, timeout=1).read()
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"сервер демо не ответил за {sec:.0f} с")


@contextlib.contextmanager
def demo_server(kind: str = "static"):
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    if kind == "static":
        proc = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                                 "--directory", str(WEB)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_up(base + "/index.html", proc)
            yield base + "/?demo"
        finally:
            proc.terminate()
            proc.wait(5)
        return
    root = Path(tempfile.mkdtemp(prefix="gp-", dir="/tmp"))      # короткий путь: сокет tmux < 100 символов
    proc = None
    try:
        proc, _ = start(root, port)
        wait_up(base + "/", proc)
        yield base + "/?demo"
    finally:
        if proc:
            proc.terminate()
            proc.wait(5)
        subprocess.run(["tmux", "-S", str(root / "s"), "kill-server"], capture_output=True)
        if not os.environ.get("GP_KEEP"):
            shutil.rmtree(root, ignore_errors=True)
