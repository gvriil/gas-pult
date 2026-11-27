"""Длинная запись (27.11: час разговора, 102 МБ → «ошибка 400», запись не легла на сервер): распознавание фоном
принимает до MAX_VOICE (300 МБ); больше — запись всё равно на диск (voice-keep), человеку — понятная причина."""
import io
import types

import pytest

from gas_pult import uploads
from gas_pult.routes import voice as rv


class FakePanel:
    def __init__(self, keep):
        self.keep, self.jobs = keep, []

    def stt_keep_stream(self, src, n, ctype):
        from gas_pult.panel.voice import VoicePart
        return VoicePart.stt_keep_stream(self, src, n, ctype)

    def _keep_dir(self):
        self.keep.mkdir(exist_ok=True)
        return self.keep

    def stt_job(self, data, ctype, uid, cloud=True):
        self.jobs.append(len(data))
        return {"job": "j1"}


def handler(panel, body: bytes):
    h = types.SimpleNamespace(panel=panel, raw=None, path="/api/stt?job=1", rfile=io.BytesIO(body),
                              headers={"Content-Length": str(len(body)), "Content-Type": "audio/webm"},
                              terms_uid=lambda: 1, space=lambda: "")
    h.body = lambda limit=uploads.MAX_BODY: body if len(body) <= limit else (_ for _ in ()).throw(ValueError("big"))
    return h


def test_limits():
    assert uploads.MAX_VOICE >= 300 << 20 > uploads.MAX_BODY and uploads.KEEP_CAP > uploads.MAX_VOICE


def test_over_50mb_goes_to_job(tmp_path, monkeypatch):
    monkeypatch.setattr(uploads, "MAX_BODY", 10)                 # «старый» предел меньше записи
    p = FakePanel(tmp_path / "keep")
    assert rv.stt(handler(p, b"x" * 50)) == {"job": "j1"} and p.jobs == [50]


def test_over_voice_limit_kept_on_disk_with_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(rv, "MAX_VOICE", 20)
    p = FakePanel(tmp_path / "keep")
    p.events = types.SimpleNamespace(event=lambda *a, **k: None)
    with pytest.raises(ValueError) as e:
        rv.stt(handler(p, b"A" * 64))
    files = list((tmp_path / "keep").iterdir())
    assert len(files) == 1 and files[0].read_bytes() == b"A" * 64 and files[0].stat().st_mode & 0o777 == 0o600
    assert "сохранена на сервере" in str(e.value) and files[0].name in str(e.value) and not p.jobs
