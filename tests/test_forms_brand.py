"""Бренд и короткое имя ссылки анкеты (владелец 23.11): анкета клиента Botsmith — без «Гаврилы» и pult; /q/<имя>."""

import json
import urllib.request

import pytest
from test_onboarding import FORM
from test_people_login import call, server  # noqa: F401

from gas_pult import onboarding

RAW = "<!doctype html><html><head><title>Анкета</title></head><body>\n<main></main>\n</body></html>".encode()


def test_brand_check_and_page():
    assert onboarding.check(FORM | {"brand": "botsmith"}) == []
    assert any("brand" in e for e in onboarding.check(FORM | {"brand": "acme"}))
    assert onboarding.page(RAW, FORM) == RAW                                   # gavrila — страница как была
    out = onboarding.page(RAW, FORM | {"title": "Опрос <x>"}, {"brand": "botsmith"}).decode()
    assert "<title>Опрос &lt;x&gt; — Botsmith</title>" in out
    assert 'og:title" content="Опрос &lt;x&gt; — Botsmith"' in out
    assert 'rel="icon" href="data:image/svg+xml' in out and 'class="brandbar"' in out and "botsmith.ru" in out
    low = out.lower()
    assert "гаврил" not in low and "pult" not in low
    assert onboarding.brand_of(FORM | {"brand": "botsmith"}, {"brand": "gavrila"}) == "gavrila"   # ссылка важнее


def test_alias_and_style(tmp_path):
    links = onboarding.Links(tmp_path)
    r = links.new("t", "Клиент")
    other = links.new("t", "Другой")
    links.style(r["id"], alias="med", brand="botsmith")
    assert links.get("med")["id"] == r["id"] and links.get(r["code"])["brand"] == "botsmith"
    for bad, msg in (("Med", "латиница"), ("m", "латиница"), ("new", "панелью")):
        with pytest.raises(ValueError, match=msg):
            links.style(other["id"], alias=bad)
    with pytest.raises(ValueError, match="занято"):
        links.style(other["id"], alias="med")
    with pytest.raises(ValueError, match="бренд"):
        links.style(r["id"], brand="acme")
    assert links.get("nope") is None and links.get("") is None
    links.draft("med", {"q1": "x"})
    assert links.get(r["code"])["draft"] == {"q1": "x"}
    links.style(r["id"], alias="")
    assert links.get("med") is None and links.get(r["code"])


def test_http_alias_brand_page(server, monkeypatch):  # noqa: F811
    panel, base = server
    (panel.cfg.data / "forms").mkdir(exist_ok=True)
    (panel.cfg.data / "forms" / "t.json").write_text(json.dumps(FORM, ensure_ascii=False))
    owner = panel.auth.issue(1)
    rid = call(base, "/api/q/new", {"form": "t", "client": "Клиент"}, owner)[1]["id"]
    onboarding.Links(panel.cfg.data).style(rid, alias="med", brand="botsmith")
    with urllib.request.urlopen(base + "/q/med") as resp:
        body = resp.read().decode()
        assert resp.status == 200 and "— Botsmith</title>" in body and "script-src 'sha256-" in resp.headers[
            "Content-Security-Policy"]
    assert "гаврил" not in body.lower()
    st, d, _ = call(base, "/api/q/med")
    assert st == 200 and d["form"]["title"] == FORM["title"] and not d["sent"]
    assert call(base, "/api/q/med/save", {"answers": {"q2": {"pick": ["офис"]}}})[0] == 200
    assert call(base, "/api/q/zz")[0] == 404
