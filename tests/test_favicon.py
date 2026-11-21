"""GAS-20: значок вкладки — svg и png 32, apple-touch-icon 180; отдаются без входа, ссылки — в панели и страницах.
20.11: знак K3 — файлы в web/brand/ (brand.py), тёмный значок вкладки — prefers-color-scheme, 192/512 — манифест."""

import struct
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from gas_pult import webapp
from gas_pult.config import Config

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
BR = WEB / "brand"


def size(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", png[16:24])


def test_files_and_links():
    assert size((BR / "favicon-32.png").read_bytes()) == (32, 32)
    assert size((BR / "favicon-32-dark.png").read_bytes()) == (32, 32)
    assert size((BR / "apple-touch-180.png").read_bytes()) == (180, 180)
    assert size((BR / "icon-192.png").read_bytes()) == (192, 192)
    assert size((BR / "icon-512.png").read_bytes()) == (512, 512)
    fav = (BR / "favicon.svg").read_text()
    assert fav.startswith("<svg") and "prefers-color-scheme:dark" in fav
    for f in ("gavrila-mark.svg", "gavrila-lockup.svg"):
        assert 'fill="currentColor"' in (BR / f).read_text(), f
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
                            ("/apple-touch-icon.png", "image/png"), ("/favicon.ico", "image/png"),
                            ("/favicon-32-dark.png", "image/png"), ("/icon-192.png", "image/png"),
                            ("/icon-512.png", "image/png"), ("/brand/gavrila-mark.svg", "image/svg+xml")):
            with urllib.request.urlopen(base + path) as r:
                assert r.status == 200 and r.headers["Content-Type"] == ctype
                assert "max-age" in r.headers["Cache-Control"]
                assert r.read()
    finally:
        srv.shutdown()


def test_mark_in_panel():
    """Знак v2 (21.11) — CSS mask из /gavrila-mark.svg: цвет — из темы, без 19 КБ векторов в ядре; три места."""
    t = (WEB / "index.html").read_text(encoding="utf-8")
    assert t.count('<span class="gmark ') == 3 and '<symbol id="gmk' not in t
    assert "mask: url(brand/gavrila-mark.svg) center / contain no-repeat;" in t and "background: currentColor;" in t
    assert 'href="/favicon-32-dark.png" sizes="32x32" type="image/png" media="(prefers-color-scheme: dark)"' in t


def test_manifest_icons():
    from gas_pult import brand
    src = [i["src"] for i in brand.manifest()["icons"]]
    assert "/icon-192.png" in src and "/icon-512.png" in src and "/apple-touch-icon.png" in src
    assert all(u in brand.ICONS for u in src)
