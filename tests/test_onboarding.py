"""Анкета клиента по ссылке (решение 0010): формат, личная ссылка без входа, черновик, отправка — ответы 0600 и
описание клиента, сообщение владельцу; чужой код — 404; ссылки и ответы — только владельцу."""

import json
import urllib.request

import pytest
from test_people_login import call, server  # noqa: F401

from gas_pult import onboarding

FORM = {"id": "t", "title": "Тест", "intro": "вступление", "rules": ["правило"], "finish": "спасибо", "sections": [
    {"id": "a", "title": "Раздел", "questions": [
        {"id": "q1", "text": "Сколько?", "options": ["мало", "много"], "required": True, "key": "volume.items",
         "setting": "объём", "hint": "зачем"},
        {"id": "q2", "text": "Где?", "multi": True, "other": True, "options": ["склад", "офис"], "key": "places.kinds"},
        {"id": "q3", "text": "Людей?", "type": "number"},
        {"id": "q4", "text": "Ещё?", "type": "text"}]}]}


def test_format_clean_profile_summary():
    assert onboarding.check(FORM) == []
    bad = json.loads(json.dumps(FORM))
    bad["sections"][0]["questions"][1]["id"] = "q1"
    bad["sections"][0]["questions"][2]["type"] = "video"
    assert len(onboarding.check(bad)) == 2
    raw = {"q1": {"pick": ["много", "мало"]}, "q2": {"pick": ["склад", "чужое"], "other": " у  партнёров "},
           "q3": "1 200", "q4": "  заметка ", "x": 1}
    a = onboarding.clean(FORM, raw)
    assert a == {"q1": {"pick": ["много"]}, "q2": {"pick": ["склад"], "other": "у партнёров"}, "q3": 1200,
                 "q4": "заметка"}
    assert onboarding.missing(FORM, {}) == ["Сколько?"] and onboarding.missing(FORM, a) == []
    p = onboarding.profile(FORM, a, "Андрей")
    assert p["settings"]["volume"]["items"] == "много" and p["settings"]["places"]["kinds"] == ["склад", "у партнёров"]
    assert p["settings"]["q3"] == 1200 and p["notes"]["q1"] == "объём"
    assert "Андрей: ответов 4 из 4" in onboarding.summary(FORM, a, "Андрей")
    pub = onboarding.public(FORM)
    assert "setting" not in pub["sections"][0]["questions"][0] and "key" not in pub["sections"][0]["questions"][0]


def test_forms_from_package_and_data(tmp_path):
    (tmp_path / "forms").mkdir()
    (tmp_path / "forms" / "t.json").write_text(json.dumps(FORM, ensure_ascii=False))
    (tmp_path / "forms" / "bad.json").write_text("{")
    fs = onboarding.forms(tmp_path)
    assert "example" in fs and "t" in fs and len(fs) == 2


def test_link_flow_http(server, monkeypatch):  # noqa: F811
    panel, base = server
    (panel.cfg.data / "forms").mkdir(exist_ok=True)
    (panel.cfg.data / "forms" / "t.json").write_text(json.dumps(FORM, ensure_ascii=False))
    told = []
    monkeypatch.setattr(panel.pult, "api", lambda m, **kw: told.append(kw["text"]), raising=False)
    owner, member = panel.auth.issue(1), panel.auth.issue(2)
    assert call(base, "/api/q/new", {"form": "t", "client": "x"}, member)[0] == 403
    st, r, _ = call(base, "/api/q/new", {"form": "t", "client": "Андрей"}, owner)
    assert st == 200 and r["path"].startswith("/q/")
    code = r["path"].split("/")[2]
    with urllib.request.urlopen(base + r["path"]) as resp:                # страница — без входа, со строгой CSP
        csp = resp.headers["Content-Security-Policy"]
        assert resp.status == 200 and b"<title>" in resp.read() and "script-src 'sha256-" in csp
    st, d, _ = call(base, f"/api/q/{code}")
    assert st == 200 and d["form"]["title"] == "Тест" and not d["sent"] and "setting" not in json.dumps(d)
    assert call(base, f"/api/q/{code}/save", {"answers": {"q2": {"pick": ["офис"]}}})[0] == 200
    assert call(base, f"/api/q/{code}")[1]["draft"] == {"q2": {"pick": ["офис"]}}     # вернулся — черновик на месте
    st, d, _ = call(base, f"/api/q/{code}/submit", {"answers": {"q2": {"pick": ["офис"]}}, "privacy": True})
    assert st == 400 and "Сколько?" in d["error"]                                         # обязательный без ответа
    st, d, _ = call(base, f"/api/q/{code}/submit", {"answers": {"q1": {"pick": ["мало"]}, "q4": "срочно"},
                                                   "privacy": True})
    assert st == 200 and told and "Андрей" in told[-1]
    rid = panel.forms_links.listing()[0]["id"]
    for f in (panel.cfg.data / "forms-answers" / f"{rid}.json", panel.cfg.data / "clients" / f"{rid}.json"):
        assert f.exists() and f.stat().st_mode & 0o777 == 0o600
    assert call(base, f"/api/q/{code}")[1]["sent"] is True
    assert call(base, f"/api/q/{code}/save", {"answers": {}})[0] == 400       # после отправки — только «Спасибо»
    assert call(base, "/api/q/" + "x" * 24)[0] == 404
    st, d, _ = call(base, "/api/q/answers?id=" + rid, None, owner)
    assert st == 200 and d["rows"][0] == {"q": "Сколько?", "a": "мало"}
    assert d["profile"]["settings"]["volume"]["items"] == "мало"
    assert call(base, "/api/q/list", None, member)[0] == 403
    assert "code" not in json.dumps(call(base, "/api/q/list", None, owner)[1])


def test_expired_link(tmp_path, monkeypatch):
    links = onboarding.Links(tmp_path)
    r = links.new("t", "К", days=1)
    code = r["code"]
    assert links.get(code)
    monkeypatch.setattr(onboarding.time, "time", lambda: 10 ** 11)
    assert links.get(code) is None
    with pytest.raises(ValueError):
        links.new("t", " ")


def test_forms_sheet_survives_empty_answer():
    """Демо 20.11: «Анкеты клиентов» падали без списка ссылок — теперь пустые списки, и в демо есть пример."""
    from pathlib import Path
    web = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
    assert "links: d?.links || []" in (web / "js/forms.js").read_text(encoding="utf-8")
    assert '"/api/q/list"' in (web / "js/demo.js").read_text(encoding="utf-8")
