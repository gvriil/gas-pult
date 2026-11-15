"""Загрузка фото быстрее (владелец 15.11: «почему так долго загружается фото»): журнал скорости, сжатие на телефоне,
прогресс, отправка без ожидания."""

from pathlib import Path

import pytest

from gas_pult import webapp


def test_upload_log_line(capsys):
    line = webapp.upload_log(223 * 1024, 52.1, "telegram")
    assert line == "upload: 223 КБ за 52.1 с (4.3 КБ/с) · telegram"
    assert "upload:" in capsys.readouterr().out
    assert webapp.upload_log(0, 0, "").endswith("· неизвестно")


def test_e2e_upload_demo():
    import importlib.util
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    pytest.importorskip("playwright.sync_api")
    web = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(web)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    spec = importlib.util.spec_from_file_location("upload_demo", Path(__file__).parent / "e2e" / "upload_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo")
    finally:
        srv.shutdown()
