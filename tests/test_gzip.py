"""Сжатие ответов панели (#191, нагрузка): страница 887 КБ и опрос /api/projects раз в 3 с шли без сжатия.
Стало: gzip, если клиент принимает; страница — один раз заранее и с ETag (перезагрузка — 304 без тела)."""

import gzip
import json
import urllib.request

from test_project_chats import server as server

from gas_pult import webapp, webauth


def get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_gzips_rule():
    big = b"x" * 5000
    assert webapp.gzips("gzip, deflate, br", "application/json; charset=utf-8", big)
    assert not webapp.gzips("br", "application/json", big)                # gzip не принимают
    assert not webapp.gzips("gzip", "audio/mpeg", big)                    # звук и картинки уже сжаты
    assert not webapp.gzips("gzip", "text/html", b"x" * 100)              # мелочь — не сжимаем
    assert webapp.gzips("deflate, gzip;q=1.0", "text/html", big)


def test_page_gzip_and_etag(server):
    _p, base, *_ = server
    plain = get(base + "/", {})
    assert plain[0] == 200 and "Content-Encoding" not in plain[1] and plain[2].startswith(b"<!doctype html")
    st, h, body = get(base + "/", {"Accept-Encoding": "gzip"})
    assert st == 200 and h["Content-Encoding"] == "gzip" and gzip.decompress(body) == plain[2]
    assert len(body) * 3 < len(plain[2])                                  # в разы меньше
    etag = h["ETag"]
    st, h, body = get(base + "/", {"Accept-Encoding": "gzip", "If-None-Match": etag})
    assert st == 304 and body == b""                                      # та же версия — без тела
    assert get(base + "/", {"If-None-Match": '"old"'})[0] == 200


def test_api_gzip(server):
    p, base, *_ = server
    tok = p.auth.issue(1)
    ck = {"Cookie": f"{webauth.COOKIE}={tok}"}
    st, h, body = get(base + "/api/projects", {**ck, "Accept-Encoding": "gzip"})
    assert st == 200 and h.get("Content-Encoding") == "gzip"
    assert json.loads(gzip.decompress(body))["projects"] is not None
    st, h, body = get(base + "/api/projects", ck)
    assert "Content-Encoding" not in h and json.loads(body)["projects"] is not None
