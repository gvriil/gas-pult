"""Боевая анкета клиента — не для проверок (штаб 23.11: боевую ссылку клиента заполнили 20 тестовыми ответами и отметкой
«отправлено»). Агент (``CLAUDECODE=1``), e2e (``GAS_PULT_E2E=1``) и запрос мимо прокси на 127.0.0.1 пишут
в боевые данные только ссылку с «ТЕСТ» в имени клиента; клиент через прокси — как раньше."""

import json
import urllib.request

import pytest
from test_onboarding import FORM
from test_people_login import call, server  # noqa: F401

from gas_pult import onboarding

ANS = {"answers": {"q1": {"pick": ["мало"]}}, "privacy": True}   # отправка — с галочкой согласия (24.11)


def test_is_test_and_guard(tmp_path, monkeypatch):
    assert onboarding.is_test({"client": "ТЕСТ клиника"}) and onboarding.is_test({"client": "qa test"})
    assert not onboarding.is_test({"client": "Клиника — бухгалтер"}) and not onboarding.is_test({})
    live = {"client": "Клиент"}
    onboarding.guard(tmp_path, live, True)                       # временная папка — не боевые данные
    monkeypatch.setattr(onboarding, "live_data", lambda d: True)
    onboarding.guard(tmp_path, live, False)                      # человек — можно
    onboarding.guard(tmp_path, {"client": "ТЕСТ клиент"}, True)  # тестовая ссылка — можно
    with pytest.raises(PermissionError, match="ТЕСТ"):
        onboarding.guard(tmp_path, live, True)


def test_links_refuse_agent_on_live(tmp_path, monkeypatch):
    links = onboarding.Links(tmp_path)
    real, test = links.new("t", "Клиника — бухгалтер")["code"], links.new("t", "ТЕСТ клиника")["code"]
    monkeypatch.setattr(onboarding, "live_data", lambda d: True)
    monkeypatch.setenv("CLAUDECODE", "1")
    for fn in (links.draft, links.submit):
        with pytest.raises(PermissionError):
            fn(real, {"q1": "x"})
    assert links.submit(test, {"q1": "x"})["sent"]
    monkeypatch.delenv("CLAUDECODE")
    monkeypatch.setenv("GAS_PULT_E2E", "1")
    with pytest.raises(PermissionError):
        links.submit(real, {"q1": "x"})
    monkeypatch.delenv("GAS_PULT_E2E")
    assert links.submit(real, {"q1": "x"})["sent"]               # служба панели (без этих переменных) — как раньше


def _post(base, path, body, xff=""):
    h = {"Content-Type": "application/json"} | ({"X-Forwarded-For": xff} if xff else {})
    req = urllib.request.Request(base + path, json.dumps(body).encode(), h)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_http_direct_local_refused_on_live(server, monkeypatch):  # noqa: F811
    panel, base = server
    (panel.cfg.data / "forms").mkdir(exist_ok=True)
    (panel.cfg.data / "forms" / "t.json").write_text(json.dumps(FORM, ensure_ascii=False))
    monkeypatch.setattr(panel.pult, "api", lambda m, **kw: None, raising=False)
    monkeypatch.delenv("CLAUDECODE", raising=False)    # проверяем только защиту по адресу
    owner = panel.auth.issue(1)
    real = call(base, "/api/q/new", {"form": "t", "client": "Клиника — бухгалтер"}, owner)[1]["path"].split("/")[2]
    test = call(base, "/api/q/new", {"form": "t", "client": "ТЕСТ клиника"}, owner)[1]["path"].split("/")[2]
    monkeypatch.setattr(onboarding, "live_data", lambda d: True)
    for act in ("save", "submit"):                         # прямо на 127.0.0.1 — агент на этой машине
        st, d = _post(base, f"/api/q/{real}/{act}", ANS)
        assert st == 403 and "ТЕСТ" in d["error"]
    assert call(base, f"/api/q/{real}")[1]["sent"] is False
    assert _post(base, f"/api/q/{test}/submit", ANS)[0] == 200
    assert _post(base, f"/api/q/{real}/submit", ANS, xff="203.0.113.7")[0] == 200   # клиент через прокси
