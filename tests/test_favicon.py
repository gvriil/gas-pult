"""GAS-20: значок вкладки — svg и png 32, apple-touch-icon 180; отдаются без входа, ссылки — в панели и страницах."""

import struct
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from gas_pult import webapp
from gas_pult.config import Config

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"


def size(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", png[16:24])


def test_files_and_links():
    assert size((WEB / "favicon-32.png").read_bytes()) == (32, 32)
    assert size((WEB / "apple-touch-icon.png").read_bytes()) == (180, 180)
    assert (WEB / "favicon.svg").read_text().startswith("<svg")
    for page in ("index.html", "offer.html", "terms.html"):
        t = (WEB / page).read_text(encoding="utf-8")
        assert 'rel="icon" href="/favicon.svg"' in t, page
        assert 'rel="apple-touch-icon" href="/apple-touch-icon.png"' in t, page


def test_served_without_login(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(webapp.Panel(Config(token="1:T", owners=[1]))))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        for path, ctype in (("/favicon.svg", "image/svg+xml"), ("/favicon-32.png", "image/png"),
                            ("/apple-touch-icon.png", "image/png"), ("/favicon.ico", "image/png")):
            with urllib.request.urlopen(base + path) as r:
                assert r.status == 200 and r.headers["Content-Type"] == ctype
                assert "max-age" in r.headers["Cache-Control"]
                assert r.read()
    finally:
        srv.shutdown()
