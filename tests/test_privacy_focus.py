"""Фокус-ссылка: согласие с политикой ПДн и условиями — до первого открытия (аудит 24.11). Без галочки — 409
``code=privacy`` и место устройства не тратится; с ней — журнал: focus:<id>, документ, версия, SHA-256."""

from test_focus import FX, call, owner, server  # noqa: F401

from gas_pult import consents, privacy, terms


def test_focus_open_needs_consent(server):  # noqa: F811
    s = server
    code, d, _ = call(s["base"], "/api/focus/new", {"w": "@1", "base": s["base"]}, owner(s))
    token = d["url"].split("#focus=")[1]
    code, r, setc = call(s["base"], "/api/focus/open", {"token": token}, "", FX)
    assert code == 409 and r["code"] == "privacy" and r["docs"]["privacy"] == privacy.VERSION and not setc
    assert not s["p"].focus.listing()[0].get("device")                            # место устройства не потрачено
    code, r, setc = call(s["base"], "/api/focus/open", {"token": token, "privacy": True}, "", FX)
    assert code == 200 and setc, r
    log = consents.listing(consents.path_of(s["p"].cfg.data), f"focus:{r['id']}")
    assert sorted((x["doc"], x["v"]) for x in log) == [("privacy", privacy.VERSION), ("terms", terms.VERSION)]
    assert all(len(x["sha256"]) == 64 for x in log)
    code, r, _ = call(s["base"], "/api/focus/open", {"token": token}, "", FX)     # второе устройство той же ссылки
    assert code == 200, r                                                          # согласие ссылки уже есть
    assert len(consents.listing(consents.path_of(s["p"].cfg.data), f"focus:{r['id']}")) == 2   # без повторов

