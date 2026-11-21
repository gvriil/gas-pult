"""Владелец 21.11: «миниатюра для PWA должна быть с лого». Превью ссылки (og:image 1200×630 — Telegram, iMessage,
WhatsApp), экраны запуска iOS (светлый и тёмный), maskable-иконка Android, цвет панели браузера по теме.
og:image — полным адресом из запроса (Host), иначе мессенджеры не показывают картинку."""
import struct
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from gas_pult import brand, webapp
from gas_pult.config import Config

BRAND = Path(__file__).resolve().parents[1] / "src/gas_pult/web/brand"


def size(png: bytes) -> tuple[int, int]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", png[16:24])


def test_files():
    assert size((BRAND / "og-1200x630.png").read_bytes()) == (1200, 630)
    assert size((BRAND / "icon-maskable-512.png").read_bytes()) == (512, 512)
    for w, h, r in brand.IPHONES:
        for t in ("light", "dark"):
            assert size((BRAND / f"splash-{w}x{h}-{t}.png").read_bytes()) == (w * r, h * r), (w, h, t)


def test_manifest_maskable():
    icons = brand.manifest()["icons"]
    assert {"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"} in icons


def get(base, path, host=None):
    req = urllib.request.Request(base + path, headers={"Host": host} if host else {})
    with urllib.request.urlopen(req) as r:
        return r.status, r.headers["Content-Type"], r.read()


def test_served_and_absolute_og(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(webapp.Panel(Config(token="1:T", owners=[1]))))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        st, ct, png = get(base, "/og.png")
        assert st == 200 and ct == "image/png" and size(png) == (1200, 630)
        assert get(base, "/splash-393x852-dark.png")[0] == 200 and get(base, "/icon-maskable-512.png")[0] == 200
        html = get(base, "/", host="pult.example.org:8443")[2].decode()
        assert '<meta property="og:image" content="https://pult.example.org:8443/og.png">' in html
        assert '<meta name="twitter:card" content="summary_large_image">' in html
        assert 'media="(prefers-color-scheme: dark)"' in html and "apple-touch-startup-image" in html
        bad = get(base, "/", host='evil.org"><script>')[2].decode()             # подделанный Host — без адреса
        assert '<meta property="og:image" content="/og.png">' in bad and "evil.org" not in bad
        assert "__ORIGIN__" not in html and "__ORIGIN__" not in bad
    finally:
        srv.shutdown()
