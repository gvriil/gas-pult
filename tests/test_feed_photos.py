"""Фото в ленте и просмотр (владелец 16.11: «возможность просмотра фотографий в чат-интерфейсе»)."""

from pathlib import Path

import pytest
from test_project_chats import call
from test_project_chats import server as server

from gas_pult import webapp


def get(base, path, tok):
    import urllib.request

    from gas_pult import webauth
    req = urllib.request.Request(base + path, headers={"Cookie": f"{webauth.COOKIE}={tok}"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, "", b""


def test_media_only_owner_only_inbox_and_drive(server, tmp_path, monkeypatch):
    import urllib.parse
    p, base, *_ = server
    inbox = p.cfg.data / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "a.jpg").write_bytes(b"\xff\xd8JPEG")
    drive = tmp_path / "drive" / "proj" / "Входящие"
    drive.mkdir(parents=True)
    (drive / "b.png").write_bytes(b"\x89PNG")
    monkeypatch.setenv("GAS_PULT_DRIVE_ROOT", str(tmp_path / "drive"))
    secret = p.cfg.data / "state.json"
    owner, member = p.auth.issue(1), p.auth.issue(2)
    q = lambda f: "/api/media?p=" + urllib.parse.quote(str(f))                 # noqa: E731
    code, ctype, data = get(base, q(inbox / "a.jpg"), owner)
    assert (code, ctype, data) == (200, "image/jpeg", b"\xff\xd8JPEG")
    assert get(base, q(drive / "b.png"), owner)[:2] == (200, "image/png")
    assert get(base, q(inbox / "a.jpg"), member)[0] == 403                    # только владельцу
    assert get(base, q(secret), owner)[0] in (400, 404)                       # не картинка и не из inbox/Диска
    assert get(base, q(str(inbox) + "/../state.json"), owner)[0] == 404       # «..» — мимо
    outside = tmp_path / "x.jpg"
    outside.write_bytes(b"\xff\xd8")
    assert get(base, q(outside), owner)[0] == 404                             # картинка, но не из разрешённых папок
    (inbox / "link.jpg").symlink_to(outside)
    assert get(base, q(inbox / "link.jpg"), owner)[0] == 404                  # ссылка наружу — мимо (realpath)
    assert call(base, "/api/meta", tok=owner)[0] == 200


def test_e2e_feed_photos():
    import importlib.util
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    pytest.importorskip("playwright.sync_api")
    web = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(web)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    spec = importlib.util.spec_from_file_location("photos_demo", Path(__file__).parent / "e2e" / "photos_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        mod.run(f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo")
    finally:
        srv.shutdown()


def test_media_types():
    assert webapp.Panel.MEDIA[".heic"] == "image/heic" and ".pdf" not in webapp.Panel.MEDIA
