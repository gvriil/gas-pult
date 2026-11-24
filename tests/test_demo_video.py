"""Ролик в демо (24.11: QR в инвест-питче ведёт на /?demo, владелец — «вход, где у нас есть кино»): файл вне git
(<данные>/media/demo.mp4), нет файла — нет кнопки; раздача с Range (206) — иначе Safari на iPhone не играет."""
import json
import urllib.request

from test_people_login import server  # noqa: F401


def get(base, path, headers=None):
    req = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_no_file_no_button(server):  # noqa: F811
    _, base = server
    st, _, body = get(base, "/api/demo/info")
    assert st == 200 and json.loads(body) == {"video": None}
    assert get(base, "/media/demo.mp4")[0] == 404


def test_video_with_ranges(server):  # noqa: F811
    panel, base = server
    f = panel.cfg.data / "media" / "demo.mp4"
    f.parent.mkdir(parents=True)
    data = bytes(range(256)) * 40                         # 10 240 байт
    f.write_bytes(data)
    assert json.loads(get(base, "/api/demo/info")[2]) == {"video": "/media/demo.mp4"}
    st, h, body = get(base, "/media/demo.mp4")
    assert st == 200 and body == data and h["Content-Type"] == "video/mp4" and h["Accept-Ranges"] == "bytes"
    st, h, body = get(base, "/media/demo.mp4", {"Range": "bytes=0-1"})       # первый запрос Safari
    assert st == 206 and body == data[:2] and h["Content-Range"] == f"bytes 0-1/{len(data)}"
    st, h, body = get(base, "/media/demo.mp4", {"Range": "bytes=10000-"})
    assert st == 206 and body == data[10000:] and h["Content-Length"] == str(len(data) - 10000)
    st, _, body = get(base, "/media/demo.mp4", {"Range": "bytes=-100"})
    assert st == 206 and body == data[-100:]
    assert get(base, "/media/demo.mp4", {"Range": "bytes=99999-"})[0] == 416


def test_page_has_button_code():
    from pathlib import Path
    web = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
    assert 'part("demovideo")' in (web / "index.html").read_text(encoding="utf-8")       # ядро — только вызов части
    js = (web / "js/demovideo.js").read_text(encoding="utf-8")
    assert 'fetch("/api/demo/info")' in js and "Смотреть, 1 мин" in js and "playsinline" in js
