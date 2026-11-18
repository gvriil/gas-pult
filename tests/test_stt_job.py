"""GAS-34 (владелец 18.11: «надо не потерять запись… долгую запись»): запись сначала на сервер, распознавание — в
фоне без лимита 90 с; не вышло — файл остаётся, «Повторить» берёт его с сервера; чужой не видит; вышло — файла нет."""

import time

import pytest

from gas_pult import voice, webapp
from gas_pult.config import Config


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path))
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    monkeypatch.setattr(p, "voice_settings", lambda: {"stt": "local", "tts": "local"})
    return p


def wait(p, jid, uid=1):
    for _ in range(100):
        r = p.stt_job_get(jid, uid)
        if r["state"] != "work":
            return r
        time.sleep(0.05)
    raise AssertionError("задание не закончилось")


def test_fail_keeps_record_and_retry_recognises(panel, monkeypatch):
    calls = []

    def flaky(path, model, timeout, data):
        calls.append(timeout)
        if len(calls) == 1:
            raise RuntimeError("служба распознавания: Broken pipe")
        return "длинная запись разговора"
    monkeypatch.setattr(voice, "transcribe_any", flaky)
    jid = panel.stt_job(b"webm-audio", "audio/webm", 1)["job"]
    r = wait(panel, jid)
    assert r["state"] == "fail" and r["kept"] and "Broken pipe" in r["error"]
    assert len(list((panel.cfg.data / "voice-keep").iterdir())) == 1          # запись на сервере, не потеряна
    assert calls[0] == webapp.STT_JOB_TIMEOUT                                # без лимита 90 с
    with pytest.raises(LookupError):
        panel.stt_job_get(jid, 2)                                            # чужой не видит
    panel.stt_retry(jid, 1)
    r = wait(panel, jid)
    assert r["state"] == "done" and r["text"] == "длинная запись разговора"
    assert not list((panel.cfg.data / "voice-keep").iterdir())               # текст есть — голос не храним
    with pytest.raises(LookupError):
        panel.stt_retry(jid, 1)


def test_old_kept_records_are_removed(panel, monkeypatch):
    monkeypatch.setattr(voice, "transcribe_any", lambda *a: "текст")
    d = panel._keep_dir()
    old = d / "old.webm"
    old.write_bytes(b"x")
    t = time.time() - (webapp.STT_KEEP_DAYS + 1) * 86400
    import os
    os.utime(old, (t, t))
    wait(panel, panel.stt_job(b"a", "audio/webm", 1)["job"])
    assert not old.exists()


def test_empty_record_rejected(panel):
    with pytest.raises(ValueError):
        panel.stt_job(b"", "audio/webm", 1)
