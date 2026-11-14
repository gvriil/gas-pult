"""Enter во время записи голоса = «Стоп и отправить» (#208)."""

from pathlib import Path

import pytest

INDEX = (Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web" / "index.html").read_text(encoding="utf-8")


def test_send_during_recording_stops_first():
    i = INDEX.index("async function sendText()")
    assert INDEX[i:i + 120].count("if (micSendNow(MIC_FULL)) return;") == 1     # первым делом — запись
    j = INDEX.index("async function sSend()")
    assert "if (micSendNow(MIC_SIMPLE)) return;" in INDEX[j:j + 120]
    f = INDEX[INDEX.index("function micSendNow(where)"):]
    f = f[:f.index("\n}\n")]
    assert "voiceStop(true)" in f and '.querySelector(".ok")?.click()' in f


def test_e2e_voice_enter():
    import importlib.util
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    pytest.importorskip("playwright.sync_api")
    web = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(web)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    e2e = Path(__file__).resolve().parent / "e2e" / "voice_enter_demo.py"
    spec = importlib.util.spec_from_file_location("voice_enter_demo", e2e)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo")
    finally:
        srv.shutdown()
