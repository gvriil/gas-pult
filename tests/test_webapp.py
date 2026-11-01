import hashlib
import hmac
import json
import urllib.parse

from gas_pult.webapp import verify

TOKEN = "123456:TEST"


def signed(fields: dict, token: str = TOKEN) -> str:
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return urllib.parse.urlencode({**fields, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()})


FIELDS = {"auth_date": "1000", "query_id": "q1", "user": json.dumps({"id": 42, "first_name": "Г"})}


def test_valid_init_data():
    assert verify(signed(FIELDS), TOKEN, now=1500)["id"] == 42


def test_wrong_token_rejected():
    assert verify(signed(FIELDS, "999:OTHER"), TOKEN, now=1500) is None


def test_tampered_user_rejected():
    data = signed(FIELDS).replace("42", "43")
    assert verify(data, TOKEN, now=1500) is None


def test_expired_rejected():
    assert verify(signed(FIELDS), TOKEN, now=1000 + 2 * 86400) is None


def test_empty_rejected():
    assert verify("", TOKEN) is None


def test_server_tz_for_panel_times(monkeypatch):
    from gas_pult import webapp
    monkeypatch.setenv("TZ", "Europe/Amsterdam")
    assert webapp.server_tz() == "Europe/Amsterdam"            # панель покажет время сервера на любом телефоне
    monkeypatch.setenv("TZ", "UTC")
    assert "/" in webapp.server_tz() or webapp.server_tz() == ""   # без имени пояса — из системы или пусто
