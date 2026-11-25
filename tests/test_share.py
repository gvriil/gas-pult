"""«Поделиться» в Ладэю (share.py): Android share_target → POST /share, iPhone → POST /api/share с токеном
устройства, свои записи — только свои."""

import http.client
import io
import json
import os
import urllib.parse
from pathlib import Path

import pytest
from test_project_chats import call
from test_project_chats import server as server

from gas_pult import brand, share, webauth

B = "gpTestBoundary42"


def form(fields: dict, files: list) -> tuple[bytes, str]:
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{B}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for name, data, typ in files:
        out.write(f'--{B}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
                  f"Content-Type: {typ}\r\n\r\n".encode() + data + b"\r\n")
    out.write(f"--{B}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={B}"


def post(base, path, body: bytes, ctype: str, headers: dict | None = None, length: int | None = None):
    u = urllib.parse.urlsplit(base)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=30)
    h = {"Content-Type": ctype, "Content-Length": str(len(body) if length is None else length), **(headers or {})}
    c.request("POST", path, body=body if length is None else b"", headers=h)
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, dict(r.getheaders()), data


def cookie(tok):
    return {"Cookie": f"{webauth.COOKIE}={tok}"}


def test_manifest_has_share_target():
    st = brand.manifest()["share_target"]
    assert st["action"] == "/share" and st["method"] == "POST" and st["enctype"] == "multipart/form-data"
    assert set(st["params"]) == {"title", "text", "url", "files"} and st["params"]["files"][0]["name"] == "files"


def test_manifest_served_with_share_target(server):
    _p, base, *_ = server
    import urllib.request
    with urllib.request.urlopen(base + "/manifest.webmanifest") as r:
        assert json.loads(r.read())["share_target"]["action"] == "/share"
    with urllib.request.urlopen(base + "/manifest.webmanifest?focus") as r:   # фокус на экране «Домой» (22.11)
        m = json.loads(r.read())
    assert m["start_url"] == "/?focus" and "share_target" not in m
    with urllib.request.urlopen(base + "/sw.js") as r:               # service worker пересылает форму с кукой
        sw = r.read().decode()
    assert '"/share"' in sw and "X-GP-SW" in sw


def test_android_share_saves_files_and_redirects(server):
    p, base, *_ = server
    tok = p.auth.issue(1)
    body, ct = form({"title": "Статья", "text": "Посмотри", "url": "https://example.org/a"},
                    [("фото.jpg", b"\xff\xd8\xff" + b"x" * 200_000, "image/jpeg"), ("пусто.txt", b"", "text/plain")])
    st, h, _ = post(base, "/share", body, ct, cookie(tok))
    assert st == 303 and h["Location"].startswith("/?share=")
    sid = h["Location"].split("=", 1)[1]
    code, d = call(base, "/api/share/list", tok=tok)
    assert code == 200 and [x["id"] for x in d["items"]] == [sid]
    it = d["items"][0]
    assert (it["title"], it["text"], it["url"]) == ("Статья", "Посмотри", "https://example.org/a")
    assert len(it["files"]) == 1 and it["files"][0]["image"] and it["files"][0]["name"] == "фото.jpg"
    f = Path(it["files"][0]["path"])
    assert f.parent == p.cfg.data / "inbox" and f.stat().st_size == 200_003     # файл целиком, пустой — пропущен
    assert call(base, "/api/meta", tok=tok)[1]["shares"] == 1
    st2, h2, _ = post(base, "/share", b"", "x", cookie(tok), length=0)          # пустое тело — честно «ошибка»
    assert st2 == 303 and h2["Location"] == "/?share=error"
    import urllib.request
    req = urllib.request.Request(f"{base}/api/share/file?id={sid}&i=0", headers=cookie(tok))
    with urllib.request.urlopen(req) as r:
        assert r.headers["Content-Type"] == "image/jpeg" and r.read()[:3] == b"\xff\xd8\xff"
    assert call(base, "/api/share/done", {"id": sid}, tok)[0] == 200
    assert call(base, "/api/share/list", tok=tok)[1]["items"] == [] and f.exists()   # разобрано, файл остался


def test_service_worker_gets_json(server):
    p, base, *_ = server
    body, ct = form({"text": "привет"}, [])
    st, _, data = post(base, "/share", body, ct, {**cookie(p.auth.issue(2)), "X-GP-SW": "1"})
    assert st == 200 and json.loads(data)["go"].startswith("/?share=")


def test_share_without_login_and_viewer(server):
    p, base, *_ = server
    body, ct = form({"text": "x"}, [])
    st, h, _ = post(base, "/share", body, ct)
    assert st == 303 and h["Location"] == "/?share=login"
    st, h, _ = post(base, "/share", body, ct, cookie(p.auth.issue(3)))      # наблюдатель — не пишет
    assert h["Location"] == "/?share=denied"
    assert call(base, "/api/share/list")[0] == 401
    assert call(base, "/api/share/devices")[0] == 401
    assert call(base, "/api/share/done", {"id": "abcdefgh"})[0] == 401


def test_too_big(server, monkeypatch):
    p, base, *_ = server
    st, h, _ = post(base, "/share", b"", "multipart/form-data; boundary=x", cookie(p.auth.issue(1)),
                    length=(50 << 20) + 1)
    assert st == 303 and h["Location"] == "/?share=big"
    t = call(base, "/api/share/devices/new", {"name": "iPhone"}, p.auth.issue(1))[1]["token"]
    st, _, _ = post(base, "/api/share", b"", "application/json", {"Authorization": f"Bearer {t}"},
                    length=(50 << 20) + 1)
    assert st == 413


def test_iphone_token_flow(server, monkeypatch):
    p, base, *_ = server
    sent = []
    monkeypatch.setattr(p.pult, "api", lambda m, **kw: sent.append((m, kw)) or {})
    monkeypatch.setattr(p, "share_notify", lambda uid, rec: sent.append((uid, rec["id"])))
    tok1, tok2 = p.auth.issue(1), p.auth.issue(2)
    st, _, _ = post(base, "/api/share", b'{"text":"x"}', "application/json")
    assert st == 401                                                       # без токена
    st, _, _ = post(base, "/api/share", b'{"text":"x"}', "application/json", {"Authorization": "Bearer gps_nope"})
    assert st == 401                                                       # чужой/выдуманный
    code, d = call(base, "/api/share/devices/new", {"name": "Мой iPhone"}, tok2)
    assert code == 200 and d["token"].startswith("gps_")
    raw = (p.cfg.data / "share_tokens.json").read_text()
    assert d["token"] not in raw and share._h(d["token"]) in raw          # на сервере — только хэш
    assert os.stat(p.cfg.data / "share_tokens.json").st_mode & 0o777 == 0o600
    auth = {"Authorization": f"Bearer {d['token']}"}
    st, _, data = post(base, "/api/share", json.dumps({"text": "Заметка", "url": "https://e.org"}).encode(),
                       "application/json", auth)
    sid = json.loads(data)["id"]
    assert st == 200 and sent[-1] == (2, sid)                              # уведомление — самому человеку
    st, _, data = post(base, "/api/share", b"text=%D1%84%D0%BE%D1%80%D0%BC%D0%B0", "application/x-www-form-urlencoded",
                       auth)
    assert st == 200
    body, ct = form({"text": "с файлом"}, [("a.pdf", b"%PDF-1.4", "application/pdf")])
    assert post(base, "/api/share", body, ct, auth)[0] == 200
    mine = call(base, "/api/share/list", tok=tok2)[1]["items"]
    assert len(mine) == 3 and {x["text"] for x in mine} == {"Заметка", "форма", "с файлом"}
    # запись участника не видна и не разбирается владельцем (и наоборот)
    assert call(base, "/api/share/list", tok=tok1)[1]["items"] == []
    assert call(base, "/api/share/done", {"id": sid}, tok1)[0] == 404
    assert call(base, f"/api/share/file?id={sid}&i=0", tok=tok1)[0] == 404
    assert call(base, "/api/share/devices", tok=tok1)[1]["devices"] == []
    assert call(base, "/api/share/devices/revoke", {"id": d["id"]}, tok1)[0] == 404   # чужое устройство не отозвать
    # отзыв — токен больше не действует
    assert call(base, "/api/share/devices/revoke", {"id": d["id"]}, tok2)[0] == 200
    assert post(base, "/api/share", b'{"text":"x"}', "application/json", auth)[0] == 401
    # человек без роли — токен не действует
    d2 = call(base, "/api/share/devices/new", {}, tok2)[1]
    p.people.remove(2)
    assert post(base, "/api/share", b'{"text":"x"}', "application/json",
                {"Authorization": f"Bearer {d2['token']}"})[0] == 401


def test_bad_filename_is_safe(server):
    p, base, *_ = server
    tok = p.auth.issue(1)
    body, ct = form({}, [("../../etc/passwd", b"root", "text/plain"), ("..\\..\\x.txt", b"y", "text/plain")])
    assert post(base, "/share", body, ct, cookie(tok))[0] == 303
    it = call(base, "/api/share/list", tok=tok)[1]["items"][0]
    inbox = (p.cfg.data / "inbox").resolve()
    for f in it["files"]:
        assert Path(f["path"]).resolve().parent == inbox and "/" not in f["name"] and "\\" not in f["name"]
    assert [f["name"] for f in it["files"]] == ["passwd", "x.txt"]


def test_multipart_parser_streams_and_limits(tmp_path):
    body, ct = form({"text": "т"}, [("a.bin", bytes(range(256)) * 1000, "application/octet-stream")])
    got = []

    def on_file(field, name, typ, part):
        data = b""
        while b := part.read(1000):
            data += b
        got.append(data)
        return {"n": len(data)}
    fields, files = share.Multipart(io.BytesIO(body), ct, len(body)).parse(on_file)
    assert fields == {"text": "т"} and files == [{"n": 256_000}] and got[0] == bytes(range(256)) * 1000
    with pytest.raises(ValueError):                                         # обрыв тела
        share.Multipart(io.BytesIO(body[:5000]), ct, len(body)).parse(on_file)
    with pytest.raises(ValueError):                                         # не multipart
        share.Multipart(io.BytesIO(b""), "text/plain", 0)
    many, ct2 = form({}, [(f"{i}.txt", b"x", "text/plain") for i in range(share.MAX_FILES + 1)])
    with pytest.raises(ValueError):
        share.Multipart(io.BytesIO(many), ct2, len(many)).parse(lambda *a: {})


def test_store_isolated(tmp_path):
    s = share.Store(tmp_path / "s.json")
    a = s.add(1, text="a")
    with pytest.raises(LookupError):
        s.get(2, a["id"])
    with pytest.raises(LookupError):
        s.done(2, a["id"])
    with pytest.raises(ValueError):
        s.add(1)                                                            # пустая запись
    assert s.pending(1) == 1 and s.pending(2) == 0


def test_ui_part_wiring():
    web = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
    core = (web / "index.html").read_text(encoding="utf-8")
    js = (web / "js" / "share.js").read_text(encoding="utf-8")
    assert 'part("share").then((m) => m.open())' in core and len(core.encode()) < 770_000
    assert "Ничего не отправится само" in js and "Файл из панели: " in js and "/api/share/done" in js
    assert "Сохранить во Входящие" in js and "Новый чат" in js and "Показывать в меню «Поделиться»" in js
    assert 'part("share").then((m) => m.devicesSheet())' in (web / "js" / "settings.js").read_text(encoding="utf-8")
