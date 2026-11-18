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
    assert [x["on"] for x in calkeys.status()] == [True, False]


@pytest.mark.parametrize("url,err", [("https://calendar.google.com/calendar/ical/me/public/basic.ics", "секретный"),
                                     ("https://evil.example/private-1/basic.ics", "Секретный адрес")])
def test_google_bad_address(url, err):
    with pytest.raises(ValueError, match=err):
        calkeys.save("google", {"url": url})


def test_icloud_check_fail_removes_file_and_hides_secret(keydir, monkeypatch):
    def boom(cfg):
        raise _core.ToolError(f"401 для {cfg['user']} с паролем {cfg['app_password']}")
    monkeypatch.setattr(cal, "_collections", boom)
    with pytest.raises(ValueError) as e:
        calkeys.save("icloud", {"user": "me@icloud.com", "password": "abcd efgh ijkl mnop"})
    assert "abcd-efgh-ijkl-mnop" not in str(e.value) and "me@icloud.com" not in str(e.value)
    assert not (keydir / "calendar-icloud.json").exists()


def test_icloud_ok_and_masked_status(keydir, monkeypatch):
    cols = [{"name": "Дом", "href": "/1/"}, {"name": "Работа", "href": "/2/"}]
    monkeypatch.setattr(cal, "_collections", lambda cfg: cols)
    r = calkeys.save("icloud", {"user": "me@icloud.com", "password": "abcdefghijklmnop"})
    assert r["checked"] == "календарей в iCloud: 2"
    rec = json.loads((keydir / "calendar-icloud.json").read_text())
    assert rec["app_password"] == "abcd-efgh-ijkl-mnop" and rec["url"] == calkeys.ICLOUD
    st = next(x for x in calkeys.status() if x["kind"] == "icloud")
    assert st["on"] and st["user"] == "me…@icloud.com"
    with pytest.raises(ValueError, match="пароль приложения"):
        calkeys.save("icloud", {"user": "me@icloud.com", "password": "MyRealPassword1"})
    calkeys.remove("icloud")
    assert not (keydir / "calendar-icloud.json").exists()
