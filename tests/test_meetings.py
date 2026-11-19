"""Протоколы встреч (GAS-36, MVP): согласие перед записью, куски из любого канала в одну встречу, «продолжение /
новая», расшифровка и аудио — на Диск (с сервера аудио уходит), агент в чате «Встречи» делает протокол."""

import time

from gas_pult import bot, meetings, voice


def test_store_pieces_transcript_and_save(tmp_path):
    t = [1000.0]
    st = meetings.Store(tmp_path / "m.json", clock=lambda: t[0])
    st.open(7)
    t[0] += 65
    st.add(7, "Решили запускать в декабре", "запись", file=str(tmp_path / "a.ogg"))
    (tmp_path / "a.ogg").write_bytes(b"ogg")
    t[0] += 60
    m = st.add(7, "Иван — смета до пятницы", "текст")
    assert meetings.transcript(m).splitlines()[0] == "[00:01] (запись) Решили запускать в декабре"
    drive = tmp_path / "drive"
    drive.mkdir()
    folder, on = meetings.save(m, drive, tmp_path / "data")
    assert on and folder.parent == drive / "Встречи" and (folder / "расшифровка.txt").read_text().count("[00:") == 2
    assert (folder / "a.ogg").exists() and not (tmp_path / "a.ogg").exists()        # аудио — на Диске, с сервера прочь
    p = meetings.prompt(folder, on)
    assert "протокол.md" in p and "Задачи: что, кто, срок" in p and "только после моего «Да»" in p


def test_no_drive_keeps_local(tmp_path):
    st = meetings.Store(tmp_path / "m.json")
    st.open(1)
    m = st.add(1, "текст", "текст")
    folder, on = meetings.save(m, None, tmp_path / "data")
    assert not on and folder.parent == tmp_path / "data" / "meetings"
    assert "Диск не подключён" in meetings.prompt(folder, on)


def make_bot(tmp_path, monkeypatch):
    p = bot.Pult.__new__(bot.Pult)
    p.meetings, p.mt_wait, p.sent, p.opened = meetings.Store(tmp_path / "m.json"), {}, [], []
    p.send = lambda chat, text, **kw: p.sent.append(text)
    p.react = lambda m, e: None
    p.cfg = type("C", (), {"data": tmp_path, "drive_root": "", "whisper_model": "small",
                           "roots": lambda self: [tmp_path / "projects"]})()
    p.open_session = lambda chat, name, path, first=None: p.opened.append((name, first))
    return p


def test_bot_flow_consent_pieces_done(tmp_path, monkeypatch):
    p = make_bot(tmp_path, monkeypatch)
    p.meeting_start(5)
    assert "предупредите участников" in p.sent[-1] and "Диктофон iPhone" in p.sent[-1] and not p.meetings.current(5)
    p.meeting_button(5, "ok")
    p.meeting_piece(5, {"text": "Обсудили цену"})
    assert "Кусок 1" in p.sent[-1]
    p.meeting_button(5, "done")
    assert p.opened and p.opened[0][0] == "meetings" and "Протокол встречи" in p.opened[0][1]
    assert not p.meetings.current(5)


def test_bot_stale_asks_continue_or_new(tmp_path, monkeypatch):
    p = make_bot(tmp_path, monkeypatch)
    p.meeting_button(5, "ok")
    monkeypatch.setattr(p.meetings, "stale", lambda chat: True)
    p.meeting_piece(5, {"text": "ещё"})
    assert "продолжение или новая" in p.sent[-1] and 5 in p.mt_wait
    monkeypatch.setattr(p.meetings, "stale", lambda chat: False)
    p.meeting_button(5, "cont")
    assert len(p.meetings.current(5)["pieces"]) == 1 and not p.mt_wait


def test_bot_audio_piece_long_timeout(tmp_path, monkeypatch):
    p = make_bot(tmp_path, monkeypatch)
    p.meeting_button(5, "ok")
    got = []
    p.api = type("A", (), {"download": lambda self, fid, d, name: tmp_path / "x.ogg"})()
    def stt(path, model, timeout, data=None):
        got.append(timeout)
        return "текст записи"
    monkeypatch.setattr(voice, "transcribe_any", stt)
    p._meeting_audio(5, {"file_id": "f1", "file_name": "Запись.m4a"})
    assert got == [40 * 60] and p.meetings.current(5)["files"] == [str(tmp_path / "x.ogg")]
    assert time.time() - p.meetings.current(5)["started"] < 60
