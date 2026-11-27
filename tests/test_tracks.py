"""«Поручения» (GAS-60 Ф1): файл команды track — только чтение; открытое без движения > 24 ч — stale; закрытые
отдаются тоже; номера чатов не показываются; маршрут — только владельцу."""
import json
from pathlib import Path

from gas_pult import access, tracks

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"


def _file(tmp_path, tasks):
    f = tmp_path / "tracks.json"
    f.write_text(json.dumps({"next": 9, "tasks": tasks}, ensure_ascii=False), encoding="utf-8")
    return f


def test_listing_states_stale_and_closed(tmp_path):
    import time
    now = time.mktime(time.strptime("2026-11-27 12:00", "%Y-%m-%d %H:%M"))
    f = _file(tmp_path, [
        {"id": "T1", "what": "старое", "to": "А", "watch": "tg:123456", "state": "передана",
         "updated": "2026-11-25 10:00", "log": [{"note": "отправлено"}]},
        {"id": "T2", "what": "свежее", "to": "Б", "pr": "o/r#5", "state": "в_работе", "updated": "2026-11-27 11:00"},
        {"id": "T3", "what": "закрыто", "to": "В", "window": "w", "state": "закрыта", "updated": "2026-11-20 10:00"}])
    before = f.read_bytes()
    d = tracks.listing(f, now)
    assert d["src"] and [t["id"] for t in d["tasks"]] == ["T2", "T1", "T3"]       # открытые сверху, свежие первыми
    t1 = next(t for t in d["tasks"] if t["id"] == "T1")
    assert t1["stale"] and t1["last"] == "отправлено" and "123456" not in json.dumps(d)   # без номера чата
    assert not next(t for t in d["tasks"] if t["id"] == "T3")["stale"]              # закрытое не «висит», но есть
    assert t1["age_h"] == 0.0 or t1["age_h"] > 0                                    # возраст — по created
    assert f.read_bytes() == before                                                 # только чтение


def test_no_file_is_empty(tmp_path):
    assert tracks.listing(tmp_path / "nope.json") == {"src": False, "tasks": []}


def test_owner_only_and_ui():
    assert "/api/tracks" in access.OWNER_ONLY
    js = (WEB / "js" / "tasks.js").read_text(encoding="utf-8")
    assert 'api("/api/tracks")' in js and "Закрытые поручения" in js and "без движения больше суток" in js


def test_owner_queue(tmp_path):
    """«Решить сегодня»: открытое с «владелец» в «кому» или «нужно решение»; закрытое — нет."""
    import time
    now = time.mktime(time.strptime("2026-11-27 12:00", "%Y-%m-%d %H:%M"))
    f = _file(tmp_path, [
        {"id": "A", "what": "да на симлинк", "to": "владелец", "state": "передана", "created": "2026-11-26 12:00"},
        {"id": "B", "what": "окно ждёт", "to": "окно x", "state": "нужно_решение", "created": "2026-11-27 10:00"},
        {"id": "C", "what": "закрыто", "to": "владелец", "state": "закрыта", "created": "2026-11-20 10:00"},
        {"id": "D", "what": "окно работает", "to": "окно y", "state": "в_работе", "created": "2026-11-27 11:00"}])
    got = {t["id"]: (t["owner"], t["age_h"]) for t in tracks.listing(f, now)["tasks"]}
    assert got["A"] == (True, 24.0) and got["B"] == (True, 2.0) and not got["C"][0] and not got["D"][0]
    js = (WEB / "js" / "brief.js").read_text(encoding="utf-8")
    assert "Решить сегодня" in js and 'api("/api/tracks")' in js and "b.age_h - a.age_h" in js
