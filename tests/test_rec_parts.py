"""Запись не теряется при блокировке (владелец 22.11): куски по ~10 с на сервер, сборка по порядку, повтор куска не
дублирует, чужой сеанс — «записи нет», обрыв — новый отрезок той же записи; панель — кусками, Wake Lock, возврат."""

import json
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import recparts, webapp, webauth
from gas_pult.config import Config

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
RID = "0f8e6a2c-1111-4222-8333-444455556666"


def test_order_dup_and_segments(tmp_path):
    p = recparts.Parts(tmp_path / "rp")
    assert p.add("1::", RID, 0, 1, b"BB", "audio/webm;codecs=opus")["dup"] is False      # пришёл раньше нулевого
    assert p.status("1::", RID)["missing"] == ["0.0"]
    with pytest.raises(ValueError, match="не хватает кусков"):
        p.assemble("1::", RID)
    p.add("1::", RID, 0, 0, b"AA")
    r = p.add("1::", RID, 0, 0, b"AA")                                                      # повтор — не дублирует
    assert r["dup"] and r["bytes"] == 4 and r["have"] == 2
    p.add("1::", RID, 1, 0, b"CC")                                                          # обрыв: новый отрезок
    segs, ctype = p.assemble("1::", RID)
    assert segs == [b"AABB", b"CC"] and ctype == "audio/webm"
    st = p.status("1::", RID)
    assert st["segs"] == [0, 1] and st["missing"] == []
    d = tmp_path / "rp" / RID
    assert d.stat().st_mode & 0o777 == 0o700 and (d / "000-00000.part").stat().st_mode & 0o777 == 0o600


def test_foreign_session_and_bad_input(tmp_path):
    p = recparts.Parts(tmp_path / "rp")
    p.add("1::", RID, 0, 0, b"AA")
    for call in (lambda: p.add("2::", RID, 0, 1, b"X"), lambda: p.status("2::", RID),
                 lambda: p.assemble("1:space:", RID), lambda: p.drop("1::f1", RID)):
        with pytest.raises(LookupError, match="записи нет"):
            call()
    assert p.status("1::", RID)["have"] == 1                                               # чужой не дописал
    for rid in ("../etc", "a", "x" * 65, "a/b/c/d/e/f"):
        with pytest.raises(ValueError):
            p.add("1::", rid, 0, 0, b"A")
    for seg, seq in ((-1, 0), (0, -1), (recparts.SEGS, 0), (0, recparts.SEQS)):
        with pytest.raises(ValueError):
            p.add("1::", RID, seg, seq, b"A")
    with pytest.raises(ValueError, match="пустой"):
        p.add("1::", RID, 0, 1, b"")


def test_size_limit_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(recparts, "MAX", 10)
    t = [1000.0]
    p = recparts.Parts(tmp_path / "rp", clock=lambda: t[0])
    p.add("1::", RID, 0, 0, b"123456")
    with pytest.raises(ValueError, match="50 МБ"):
        p.add("1::", RID, 0, 1, b"123456")
    t[0] += recparts.KEEP + 1
    p.add("1::", "aaaaaaaa-new", 0, 0, b"A")                                              # новый сеанс чистит брошенные
    assert not (tmp_path / "rp" / RID).exists()


@pytest.fixture
def srv(monkeypatch):
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.accept(1)
    p.people.set_country(1, chosen="NL")
    heard = []

    def fake(f, cloud):
        heard.append(f.read_bytes())
        return f"отрезок {len(heard)}"
    monkeypatch.setattr(p, "_stt_file", fake)
    s = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield {"p": p, "base": f"http://127.0.0.1:{s.server_address[1]}", "own": f"{webauth.COOKIE}={p.auth.issue(1)}",
           "heard": heard}
    s.shutdown()


def call(s, path, body=None, raw=None, cookie=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(s["base"] + path, data, {"Content-Type": "audio/webm" if raw is not None else
                                                           "application/json", "Cookie": s["own"] if cookie is None
                                                           else cookie})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_http_chunks_then_finish(srv):
    s = srv
    for seg, seq, b in ((0, 0, b"A0"), (0, 1, b"A1"), (0, 1, b"A1"), (1, 0, b"B0")):
        code, r = call(s, f"/api/rec/chunk?id={RID}&seg={seg}&seq={seq}", raw=b)
        assert code == 200, r
    code, st = call(s, f"/api/rec/status?id={RID}")
    assert code == 200 and st["have"] == 3 and st["segs"] == [0, 1]
    assert call(s, f"/api/rec/chunk?id={RID}&seg=0&seq=2", raw=b"x", cookie="")[0] == 401   # без входа — нет
    code, r = call(s, "/api/rec/finish", {"id": RID})
    assert code == 200 and r["segs"] == 2 and r["job"]
    for _ in range(100):
        j = s["p"].stt_jobs[r["job"]]
        if j["state"] != "work":
            break
        time.sleep(0.02)
    assert j["state"] == "done" and j["text"] == "отрезок 1 отрезок 2" and s["heard"] == [b"A0A1", b"B0"]
    assert not list((s["p"].cfg.data / "voice-keep").glob(r["job"] + "*"))               # текст есть — голос удалён
    assert call(s, "/api/rec/finish", {"id": RID})[0] == 404                               # сеанса больше нет
    assert call(s, f"/api/rec/chunk?id={RID}&seg=0&seq=x", raw=b"x")[0] == 400


def test_panel_records_in_slices_and_resumes():
    """Панель: MediaRecorder кусками (timeslice) → /api/rec/chunk; Wake Lock на время записи и снятие по «Стоп»;
    возврат на страницу — новый отрезок и «Запись прервалась на N с, продолжаю»; честная подсказка для iPhone."""
    core = (WEB / "index.html").read_text(encoding="utf-8")
    part = (WEB / "js" / "recsafe.js").read_text(encoding="utf-8")
    job = (WEB / "js" / "voicejob.js").read_text(encoding="utf-8")
    mic = core[core.index("async function toggleMic()"):core.index("// Распознавание: строка остаётся на месте")]
    assert 'part("recsafe")' in mic and "r.start(S ? RS.SLICE : undefined)" in mic and "S?.push(e.data)" in mic
    assert "visibilitychange" in mic and "S.next()" in mic and "RS.resumed(" in mic and "requestData()" in mic
    assert re.search(r"SLICE = 10000", part) and "/api/rec/chunk?id=" in part and "/api/rec/finish" in part
    assert 'navigator.wakeLock.request("screen")' in part and "S.lock?.release()" in part
    assert "Запись прервалась на" in part and "продолжаю" in part
    assert "На iPhone при блокировке запись останавливается" in part and "Диктофон → Поделиться → Гаврила" in part
    assert "blob.rec.finish()" in job                                                       # куски — с сервера
    assert '"/api/rec/chunk"' in (Path(webapp.__file__).read_text(encoding="utf-8"))
