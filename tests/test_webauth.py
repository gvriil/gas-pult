import pytest

from gas_pult import webauth
from gas_pult.webauth import Auth


def test_code_login_and_logout(tmp_path):
    a = Auth(tmp_path / "s.json")
    rid, code = a.start()
    assert len(code) == 6 and code.isdigit()
    token = a.verify(rid, code, "test")
    assert a.check(token) and not a.check("чужой")
    assert code not in (tmp_path / "s.json").read_text() and token not in (tmp_path / "s.json").read_text()
    a.logout(token)
    assert not a.check(token)


def test_code_is_single_use_and_limited(tmp_path):
    a = Auth(tmp_path / "s.json")
    rid, code = a.start()
    for _ in range(webauth.CODE_TRIES):
        with pytest.raises(ValueError):
            a.verify(rid, "000000" if code != "000000" else "111111")
    with pytest.raises(ValueError, match="попыток"):
        a.verify(rid, code)                     # после 5 ошибок верный код уже не спасает


def test_start_rate_limit(tmp_path):
    a = Auth(tmp_path / "s.json")
    for _ in range(webauth.START_LIMIT[0]):
        a.start()
    with pytest.raises(ValueError, match="много"):
        a.start()


def test_cookie_helpers():
    assert webauth.cookie_value("a=1; gp_session=xyz; b=2") == "xyz"
    assert "HttpOnly" in webauth.set_cookie("t") and "Secure" in webauth.set_cookie("t")
