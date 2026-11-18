"""Ключи календарей из «Интеграций» (штаб 18.11: владелец секреты в чат не шлёт): поле → файл 0600 коннектора →
проверка подключения; значение не возвращается ни в ответе, ни в ошибке; проверка не прошла — файла нет."""

import json
import stat

import pytest

from gas_pult import calkeys
from gas_pult.connectors import _core
from gas_pult.connectors import calendar_mcp as cal

URL = "https://calendar.google.com/calendar/ical/me%40example.com/private-0123456789abcdef/basic.ics"


@pytest.fixture(autouse=True)
def keydir(tmp_path, monkeypatch):
    monkeypatch.setenv("GAS_CAL_KEY_DIR", str(tmp_path / "keys"))
    return tmp_path / "keys"


def test_google_saved_0600_and_checked(keydir, monkeypatch):
    monkeypatch.setattr(cal, "_ics", lambda cfg: "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:1\nDTSTART:20261118T100000Z\n"
                                                 "SUMMARY:Встреча\nEND:VEVENT\nEND:VCALENDAR\n")
    r = calkeys.save("google", {"url": URL})
    assert r["checked"] == "событий в календаре: 1" and URL not in json.dumps(r)
    f = keydir / "calendar-google.json"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600 and json.loads(f.read_text())["kind"] == "ics"
    assert [x["on"] for x in calkeys.status()] == [True]


@pytest.mark.parametrize("url,err", [("https://calendar.google.com/calendar/ical/me/public/basic.ics", "секретный"),
                                     ("https://evil.example/private-1/basic.ics", "Секретный адрес")])
def test_google_bad_address(url, err):
    with pytest.raises(ValueError, match=err):
        calkeys.save("google", {"url": url})


def test_icloud_is_not_here():
    with pytest.raises(ValueError, match="Календарь iCloud"):
        calkeys.save("icloud", {"user": "me@icloud.com", "password": "x"})


def test_check_fail_removes_file_and_hides_address(keydir, monkeypatch):
    def boom(cfg):
        raise _core.ToolError(f"404 для {cfg['url']}")
    monkeypatch.setattr(cal, "_ics", boom)
    with pytest.raises(ValueError) as e:
        calkeys.save("google", {"url": URL})
    assert URL not in str(e.value) and "[скрыто]" in str(e.value)
    assert not (keydir / "calendar-google.json").exists()
