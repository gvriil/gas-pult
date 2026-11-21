"""«Отзыв» в пульте (штаб 21.11): текст и снимок → файл в feedback/ и задача штабу; «где застревают» — в отчёте
функций, только id экранов."""
import base64
import json
import os
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import features, feedback, webapp, webauth
from gas_pult.config import Config

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 64).decode()
WEB = Path(webapp.__file__).parent / "web"


def test_save_text_and_shot_private(tmp_path):
    shot = "data:image/png;base64," + PNG
    rec = feedback.save(tmp_path, 5, "Анна", "  не нашла время брифинга ", "sheet.brief", shot)
    d = tmp_path / "feedback"
    assert rec["text"] == "не нашла время брифинга" and rec["screen"] == "sheet.brief" and rec["shot"].endswith(".png")
    for f in d.iterdir():
        assert oct(os.stat(f).st_mode & 0o777) == "0o600"
    assert json.loads(Path(rec["file"]).read_text())["name"] == "Анна"
    t = feedback.task(rec)
    assert t["title"].startswith("Отзыв: не нашла") and t["link"] == rec["file"] and t["kind"] == "check"


@pytest.mark.parametrize("bad", ["data:image/png;base64," + base64.b64encode(b"GIF89a").decode(),
                                 "data:text/html;base64,PGI+", "javascript:alert(1)"])
def test_bad_shot_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        feedback.save(tmp_path, 1, "", "текст", "", bad)


def test_empty_refused_and_screen_id_only(tmp_path):
    with pytest.raises(ValueError):
        feedback.save(tmp_path, 1, "", "   ", "", "")
    assert feedback.save(tmp_path, 1, "", "x", "<script>", "")["screen"] == ""


@pytest.fixture
def server(monkeypatch):
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.add(3, "viewer", "Ольга")
    for uid in (1, 3):
        p.people.accept(uid)
        p.people.set_country(uid, chosen="NL")
    sent = []
    monkeypatch.setattr(p.pult, "broadcast", lambda text, **kw: sent.append(text))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield p, srv.server_address[1], sent
    srv.shutdown()


def post(port, path, body, tok=""):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("POST", path, json.dumps(body), {"Cookie": f"{webauth.COOKIE}={tok}" if tok else "",
                                               "Content-Type": "application/json"})
    r = c.getresponse()
    out = (r.status, json.loads(r.read() or b"{}"))
    c.close()
    return out


def test_http_viewer_sends_task_and_owner_told(server):
    p, port, sent = server
    assert post(port, "/api/feedback", {"text": "x"})[0] == 401
    st, d = post(port, "/api/feedback", {"text": "кнопка «Сегодня» долго грузится", "screen": "home"},
                 p.auth.issue(3))
    assert st == 200 and d["ok"]
    t = next(x for x in p.task_list() if x["id"] == d["task"])
    assert t["title"].startswith("Отзыв: кнопка") and t["by"] == "feedback"
    assert sent and "Ольга" in sent[0] and "экран home" in sent[0]
    sent.clear()
    assert post(port, "/api/feedback", {"text": "моё"}, p.auth.issue(1))[0] == 200 and sent == []   # свой — не шлём


def test_stuck_in_report(tmp_path):
    u = features.Uses(tmp_path / "f.json")
    u.record(["stuck.err:sheet.brief", "stuck.help:home", "home.projects"], now=1_000_000)
    r = features.report(u, now=1_000_100)
    assert dict(r["stuck"]) == {"err:sheet.brief": 1, "help:home": 1}
    assert all(not k.startswith("stuck.") for k, _, _ in r["top"])
    assert "## Где застревают" in features.markdown(r) and "`err:sheet.brief`: 1" in features.markdown(r)


def test_entry_points_and_marks():
    st = (WEB / "js/settings.js").read_text(encoding="utf-8")
    assert '{ label: "Отзыв", icon: "chat"' in st and 'part("feedback")' in st
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'id: "feedback", label: "Отзыв"' in html
    assert 'useMark("stuck.err:" + (USE.cur || "home"))' in html
    assert 'useMark("stuck.help:" + (USE.cur || "home"))' in html
    js = (WEB / "js/feedback.js").read_text(encoding="utf-8")
    assert '"/api/feedback"' in js and 'accept="image/*"' in js
