"""Протокол встречи уровня Plaud (владелец 22.11): оглавление с проверкой времени, «Что сделать», карточка-превью
(SVG, текст экранирован), ссылка на один протокол — по ней нельзя получить другие протоколы и остальное API."""

import json
import os
import threading
import time
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gas_pult import access, focus, meetings, webapp, webauth
from gas_pult.config import Config


def test_chapters_checked_and_bad_dropped():
    raw = [{"start": 0, "end": 120, "topic": "Знакомство"},
           {"start": "02:00", "end": "05:00", "topic": "Смета"},
           {"start": 100, "end": 200, "topic": "Назад во времени"},            # раньше предыдущей — прочь
           {"start": 290, "end": 280, "topic": "Конец раньше начала"},         # прочь
           {"start": 400, "topic": ""},                                        # без темы — прочь
           {"start": 400, "topic": "Сроки"},                                    # конец — до следующей
           {"start": "x", "end": 1, "topic": "Чепуха"},
           {"start": 500, "end": 9999, "topic": "Дальше записи"},             # за длительностью — прочь
           {"start": 550, "topic": "Итоги"},                                    # конец — до конца записи
           "строка", None]
    ch = meetings.parse_chapters(raw, 600)
    assert [c["topic"] for c in ch] == ["Знакомство", "Смета", "Сроки", "Итоги"]
    assert [(c["start"], c["end"]) for c in ch] == [(0, 120), (120, 300), (400, 550), (550, 600)]
    assert meetings.parse_chapters({"start": 0}, 600) == [] and meetings.parse_chapters(None, None) == []
    assert meetings.parse_chapters([{"start": 700, "topic": "после конца"}], 600) == []
    assert meetings.parse_chapters([{"start": 700, "topic": "длительность неизвестна"}], None)[0]["end"] is None
    assert meetings.seconds("1:02:03") == 3723 and meetings.seconds(True) is None and meetings.seconds(-1) is None


def test_actions_parsed():
    a = meetings.parse_actions([{"what": "Смета", "who": "Иван", "due": "2026-11-28"}, {"what": ""},
                                {"what": "Договор", "who": "Пётр", "due": "до пятницы"}, "Позвонить в банк", 5])
    assert a == [{"what": "Смета", "who": "Иван", "due": "2026-11-28"},
                 {"what": "Договор", "who": "Пётр", "due": "", "when": "до пятницы"},
                 {"what": "Позвонить в банк", "who": "", "due": ""}]


def test_card_escapes_text():
    v = {"gist": '<script>alert(1)</script> & "кавычки"', "title": "Тема <b>", "started": time.time(), "dur": 1800,
         "chapters": [{}, {}]}
    svg = meetings.card_svg(v, '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 20"><path d="M0 0"/></svg>')
    assert "<script>" not in svg and "&lt;script&gt;" in svg and "&amp;" in svg and "<b>" not in svg
    assert svg.startswith("<svg") and "30 мин" in svg and "глав: 2" in svg and 'viewBox="0 0 10 20"' in svg
    long = meetings.card_svg({"gist": "слово " * 200}, "")
    assert long.count("<tspan x=") == 4 and "…" in long          # строки; ещё один tspan — красная «э» знака


def silent_wav(p: Path, sec: int = 3):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(8000)
        w.writeframes(b"\x80" * 8000 * sec)


def make_meeting(root: Path, name: str, gist: str, wav: bool = True) -> Path:
    d = root / "Встречи" / name
    d.mkdir(parents=True)
    (d / "протокол.md").write_text(f"# {gist}\n\n## Что сделать\n- смета", encoding="utf-8")
    (d / "расшифровка.txt").write_text("секретная расшифровка", encoding="utf-8")
    (d / meetings.JSON_NAME).write_text(json.dumps({"gist": gist, "chapters": [
        {"start": 0, "end": 1, "topic": "Начало"}, {"start": 1, "end": 3, "topic": "Итоги"},
        {"start": 2, "end": 99, "topic": "плохая"}], "actions": [{"what": "смета", "who": "Иван"}]}), encoding="utf-8")
    if wav:
        silent_wav(d / "запись.wav")
        (d / meetings.META).write_text(json.dumps({"dur": meetings.audio_seconds(d / "запись.wav")}))
    return d


def test_save_records_duration_and_view(tmp_path):
    st = meetings.Store(tmp_path / "m.json")
    st.open(1)
    silent_wav(tmp_path / "a.wav", 4)
    m = st.add(1, "текст встречи", "запись", file=str(tmp_path / "a.wav"))
    folder, _ = meetings.save(m, None, tmp_path / "data")
    assert meetings.saved_dur(folder) == 4.0
    assert "4 с" in meetings.prompt(folder, False, [], 4.0) and meetings.JSON_NAME in meetings.prompt(folder, False)
    v = meetings.view(folder)
    assert v["id"] == meetings.mid_of(folder.name) and v["audio"] and not v["ready"] and v["transcript"]
    assert meetings.listing(None, tmp_path / "data")[0]["id"] == v["id"]
    with pytest.raises(LookupError):
        meetings.find("../../etc", None, tmp_path / "data")


@pytest.fixture
def srv():
    drive = Path(os.environ["GAS_PULT_DRIVE_ROOT"])
    a = make_meeting(drive, "2026-11-20 10-00 встреча", "Запуск в декабре")
    make_meeting(drive, "2026-11-21 11-30 встреча", "Чужой протокол")
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    p.people.accept(1)
    p.people.set_country(1, chosen="NL")
    s = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield {"p": p, "base": f"http://127.0.0.1:{s.server_address[1]}", "tok": p.auth.issue(1), "a": a}
    s.shutdown()


def call(base, path, body=None, cookie="", headers=None):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "Cookie": cookie, **(headers or {})})
    try:
        with urllib.request.urlopen(req) as r:
            data = r.read()
            ct = r.headers.get("Content-Type", "")
            return r.status, (json.loads(data) if ct.startswith("application/json") else data), \
                r.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), ""


FX = {focus.HEADER: "1"}


def test_owner_sees_list_view_card_audio(srv):
    own = f"{webauth.COOKIE}={srv['tok']}"
    code, d, _ = call(srv["base"], "/api/meetings", None, own)
    assert code == 200 and [x["id"] for x in d["meetings"]] == ["20261121-1130", "20261120-1000"]
    code, v, _ = call(srv["base"], "/api/meeting?id=20261120-1000", None, own)
    assert code == 200 and v["gist"] == "Запуск в декабре" and v["dur"] == 3.0
    assert [c["topic"] for c in v["chapters"]] == ["Начало", "Итоги"] and v["actions"][0]["who"] == "Иван"
    code, svg, _ = call(srv["base"], "/api/meeting/card?id=20261120-1000", None, own)
    assert code == 200 and svg.startswith(b"<svg") and "Запуск в декабре".encode() in svg
    code, wav, _ = call(srv["base"], "/api/meeting/audio?id=20261120-1000", None, own)
    assert code == 200 and wav[:4] == b"RIFF"
    for path in ("/api/meetings", "/api/meeting?id=20261120-1000"):
        assert call(srv["base"], path)[0] == 401                       # без входа — нет
    assert "/api/meeting/share" in access.OWNER_ONLY and "/api/meeting/share" not in access.ADMIN_OK


def share(srv, mid="20261120-1000"):
    own = f"{webauth.COOKIE}={srv['tok']}"
    code, d, _ = call(srv["base"], "/api/meeting/share", {"id": mid, "base": srv["base"]}, own)
    assert code == 200 and d["mode"] == "meeting", d
    token = d["url"].split("#focus=")[1]
    code, r, setc = call(srv["base"], "/api/focus/open", {"token": token}, "", FX)
    assert code == 200 and r["mode"] == "meeting", r
    return d, token, setc.split(";")[0]


def test_public_link_shows_only_its_protocol(srv):
    _, _, cookie = share(srv)
    code, v, _ = call(srv["base"], "/api/mt", None, cookie, FX)
    assert code == 200 and v["gist"] == "Запуск в декабре" and v["md"].startswith("# Запуск")
    assert "transcript" not in v and "links" not in v and "секретная" not in json.dumps(v, ensure_ascii=False)
    code, wav, _ = call(srv["base"], "/api/mt/audio?id=20261121-1130", None, cookie, FX)   # id из запроса не берём
    assert code == 200 and wav[:4] == b"RIFF"
    code, svg, _ = call(srv["base"], "/api/mt/card?id=20261121-1130", None, cookie, FX)
    assert code == 200 and b"\xd0" in svg and "Чужой".encode() not in svg
    for path, body in (("/api/meetings", None), ("/api/meeting?id=20261121-1130", None),
                       ("/api/meeting/audio?id=20261121-1130", None), ("/api/meeting/card?id=20261121-1130", None),
                       ("/api/sessions", None), ("/api/meta", None), ("/api/tasks", None), ("/api/focus/list", None),
                       ("/api/history?w=@1", None), ("/api/media?p=/etc/passwd", None),
                       ("/api/meeting/share", {"id": "20261121-1130"}), ("/api/tasks/add", {"title": "x"}),
                       ("/api/send", {"w": "@1", "text": "x"}), ("/api/people", None)):
        code, r, _ = call(srv["base"], path, body, cookie, FX)
        assert code == 403 and r["code"] == "focus_scope", (path, code, r)
        code, r, _ = call(srv["base"], path, body, cookie)                # и без заголовка фокуса — не вход
        assert code in (401, 403), (path, code, r)
    # другой протокол — только своей ссылкой; эта ссылка его не отдаёт
    _, _, other = share(srv, "20261121-1130")
    assert call(srv["base"], "/api/mt", None, other, FX)[1]["gist"] == "Чужой протокол"
    assert call(srv["base"], "/api/mt", None, cookie, FX)[1]["gist"] == "Запуск в декабре"


def test_public_link_many_devices_listed_and_revoked(srv):
    d, token, cookie = share(srv)
    for _ in range(3):                                                     # участники встречи — разные устройства
        assert call(srv["base"], "/api/focus/open", {"token": token}, "", FX)[0] == 200
    own = f"{webauth.COOKIE}={srv['tok']}"
    links = call(srv["base"], "/api/focus/list", None, own)[1]["links"]
    assert links[0]["mode"] == "meeting" and links[0]["mt"] == "20261120-1000" and links[0]["devices"] == 4
    assert call(srv["base"], "/api/meeting?id=20261120-1000", None, own)[1]["links"][0]["id"] == d["id"]
    assert call(srv["base"], "/api/focus/revoke", {"id": d["id"]}, own)[0] == 200
    code, r, _ = call(srv["base"], "/api/mt", None, cookie, FX)
    assert code == 410 and "отозвал" in r["error"]


def test_owner_opening_public_link_gets_public_view(srv):
    """Владелец открыл ссылку на протокол у себя — видит то же, что участник (не переход на чат)."""
    own = f"{webauth.COOKIE}={srv['tok']}"
    _, token, _ = share(srv)
    code, r, _ = call(srv["base"], "/api/focus/open", {"token": token}, own, FX)
    assert code == 200 and r.get("mode") == "meeting" and not r.get("owner_here")


def test_meeting_link_store(tmp_path):
    f = focus.Focus(tmp_path / "focus.json")
    link = f.new({"id": "", "path": "", "name": "Встреча"}, 1, ttl=focus.MEETING_TTL, mode=focus.MEETING,
                 mt="20261120-1000")
    c1, rec = f.open(link["token"], "")
    assert rec["mt"] == "20261120-1000" and focus.Focus.is_meeting(rec) and not focus.Focus.is_demo(rec)
    assert f.by_cookie(c1)["mt"] == "20261120-1000" and not f.set_browser(link["id"], True)
    assert f.end_window("") == 0 and f.by_cookie(c1)                      # закрытие окон её не гасит
