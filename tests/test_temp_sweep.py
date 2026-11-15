"""Остатки оборванной озвучки убираются сами (аудит #189): ``*.tmp.wav`` и пустые ``*.mp3`` старше часа — в папке
данных и её подпапках первого уровня. Озвучка с содержимым (кеш голосов) и ``inbox`` (#217) не трогаются."""

import os

from gas_pult import webapp
from gas_pult.config import Config

T0 = 1_800_000_000
HOUR = 3600


def put(path, data=b"", age=2 * HOUR):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (T0 - age, T0 - age))
    return path


def test_sweep_temp_removes_only_old_leftovers(tmp_path):
    old_wav = put(tmp_path / "web-1.tmp.wav", b"RIFF")
    old_mp3 = put(tmp_path / "web-1.mp3")
    sub_wav = put(tmp_path / "tts" / "x.tmp.wav", b"RIFF")
    keep = [put(tmp_path / "web-2.tmp.wav", b"RIFF", age=60),               # свежий — озвучка ещё идёт
            put(tmp_path / "web-2.mp3", age=60),
            put(tmp_path / "voice-preview" / "xenia.mp3", b"ID3"),          # кеш голоса — не мусор
            put(tmp_path / "inbox" / "old.tmp.wav", b"RIFF"),               # входящие — своя очистка (#217)
            put(tmp_path / "inbox" / "empty.mp3"),
            put(tmp_path / "a" / "b" / "deep.tmp.wav", b"RIFF"),             # глубже первого уровня не ходим
            put(tmp_path / "note.wav", b"RIFF")]
    gone = webapp.sweep_temp(tmp_path, T0, HOUR)
    assert sorted(gone) == sorted([old_wav, old_mp3, sub_wav])
    assert all(p.exists() for p in keep) and not any(p.exists() for p in gone)
    assert webapp.sweep_temp(tmp_path / "нет", T0, HOUR) == []


def test_temp_tick_hourly(tmp_path):
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    put(p.cfg.data / "web-a.tmp.wav", b"RIFF")
    assert [f.name for f in p.temp_tick(T0)] == ["web-a.tmp.wav"]           # первый вызов — сразу
    put(p.cfg.data / "web-b.tmp.wav", b"RIFF")
    assert p.temp_tick(T0 + HOUR - 60) == []                                # час не прошёл
    assert [f.name for f in p.temp_tick(T0 + HOUR)] == ["web-b.tmp.wav"]
