"""Политика ПДн, согласие и одна версия условий (аудит 24.11): /privacy — 200, версия и дата из privacy.VERSION,
плашка «Черновик», оператор — из operator.toml вне git (нет — «[ЗАПОЛНИТЬ]»); /terms — версия из terms.VERSION;
анкета /q/ и фокус-ссылка — без галочки согласия сервер отказывает, с ней — журнал: документ, версия, SHA-256."""

import hashlib
import json
import urllib.request
from pathlib import Path

import pytest
from test_onboarding import FORM
from test_people_login import call, server  # noqa: F401

from gas_pult import consents, privacy, terms

ROOT = Path(__file__).resolve().parents[1]
OP = 'name = "ТЕСТ Оператор"\ninn = "000000000000"\nemail = "op@example.test"\n'


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=10) as r:
        return r.status, r.read()


def test_dates_and_fill():
    assert terms.date_ru("2026-11-02") == "2 ноября 2026 года" and terms.date_en("2026-11-24") == "24 November 2026"
    out = terms.fill(b"{{VERSION}}|{{DATE_RU}}|{{X}}", "2026-01-31", {"X": "y"})
    assert out == "2026-01-31|31 января 2026 года|y".encode()


def test_operator_from_file_or_fill(tmp_path):
    assert privacy.operator(tmp_path) == dict.fromkeys(privacy.FIELDS, "")           # нет файла
    (tmp_path / "operator.toml").write_text("[operator]\n" + OP + 'phone = "<b>"\n', encoding="utf-8")
    op = privacy.operator(tmp_path)
    assert op["name"] == "ТЕСТ Оператор" and op["ogrnip"] == "" and op["phone"] == "<b>"
    raw = b"{{OP_NAME}} {{OP_OGRNIP}} {{OP_PHONE}}"
    out = privacy.page(raw, tmp_path).decode()
    assert "ТЕСТ Оператор" in out and privacy.FILL in out and "&lt;b&gt;" in out and "<b>" not in out
    (tmp_path / "operator.toml").write_text("name = [", encoding="utf-8")            # ошибка в файле — не падаем
    assert privacy.operator(tmp_path)["name"] == ""


def test_privacy_page(server, tmp_path, monkeypatch):  # noqa: F811
    _p, base = server
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path))
    st, body = get(base, "/privacy")
    html = body.decode()
    assert st == 200 and f"версия {privacy.VERSION}" in html and terms.date_ru(privacy.VERSION) in html
    assert f"version {privacy.VERSION}" in html and terms.date_en(privacy.VERSION) in html
    assert 'id="ru"' in html and 'id="en"' in html and "{{" not in html
    assert privacy.PUBLISHED is False and 'class="draft-flag"' in html and 'class="draft-flag" hidden' not in html
    assert "Черновик — не опубликовано" in html and html.count(privacy.FILL) >= len(privacy.FIELDS)
    assert "152-ФЗ" in html and "GDPR" in html and "Роскомнадзор" in html
    (tmp_path / "operator.toml").write_text(OP, encoding="utf-8")
    html = get(base, "/privacy")[1].decode()
    assert "ТЕСТ Оператор" in html and "op@example.test" in html               # файл прочитан на запрос
    monkeypatch.setattr(privacy, "PUBLISHED", True)
    assert 'class="draft-flag" hidden' in get(base, "/privacy")[1].decode()      # «да» владельца — плашки нет


def test_terms_version_single_source(server):  # noqa: F811
    _p, base = server
    html = get(base, "/terms")[1].decode()
    assert f"Редакция от {terms.date_ru(terms.VERSION)} (версия {terms.VERSION})" in html
    assert f"Revision of {terms.date_en(terms.VERSION)} (version {terms.VERSION})" in html and "{{" not in html
    raw = (ROOT / "src/gas_pult/web/terms.html").read_text(encoding="utf-8")
    assert "Редакция от {{DATE_RU}}" in raw and "ноября 2026 года." not in raw.split("Редакция от", 1)[1][:40]


def test_no_operator_data_in_repo():
    raw = (ROOT / "src/gas_pult/web/privacy.html").read_text(encoding="utf-8")
    for k in privacy.FIELDS:
        assert "{{OP_" + k.upper() + "}}" in raw
    assert not (ROOT / "operator.toml").exists()


def _anketa(panel, base, monkeypatch):
    (panel.cfg.data / "forms").mkdir(exist_ok=True)
    (panel.cfg.data / "forms" / "t.json").write_text(json.dumps(FORM, ensure_ascii=False))
    monkeypatch.setattr(panel.pult, "api", lambda m, **kw: None, raising=False)
    r = call(base, "/api/q/new", {"form": "t", "client": "ТЕСТ клиника"}, panel.auth.issue(1))[1]
    return r["path"].split("/")[2], r["id"]


def test_anketa_submit_needs_consent(server, monkeypatch):  # noqa: F811
    panel, base = server
    code, rid = _anketa(panel, base, monkeypatch)
    ans = {"q1": {"pick": ["мало"]}}
    assert call(base, f"/api/q/{code}/save", {"answers": ans})[0] == 200          # черновик — без галочки
    for body in ({"answers": ans}, {"answers": ans, "privacy": "yes"}):
        st, d, _ = call(base, f"/api/q/{code}/submit", body)
        assert st == 409 and d["code"] == "privacy" and "Согласен(на)" in d["error"], d
        assert d["docs"] == {"privacy": privacy.VERSION, "terms": terms.VERSION}
    assert call(base, f"/api/q/{code}")[1]["sent"] is False
    st, d, _ = call(base, f"/api/q/{code}/submit", {"answers": ans, "privacy": True})
    assert st == 200, d
    log = consents.listing(consents.path_of(panel.cfg.data), f"form:{rid}")
    assert {r["doc"]: r["v"] for r in log} == {"privacy": privacy.VERSION, "terms": terms.VERSION}
    page = get(base, "/privacy")[1]
    assert next(r for r in log if r["doc"] == "privacy")["sha256"] == hashlib.sha256(page).hexdigest()
    assert next(r for r in log if r["doc"] == "terms")["sha256"] == hashlib.sha256(get(base, "/terms")[1]).hexdigest()
    assert all(r["at"] > 0 for r in log)


def test_q_page_has_separate_checkbox():
    q = (ROOT / "src/gas_pult/web/q.html").read_text(encoding="utf-8")
    assert 'id="agree"' in q and "Согласен(на) на обработку персональных данных по" in q
    assert 'href="/privacy" target="_blank" rel="noopener"' in q and 'href="/terms" target="_blank" rel="noopener"' in q
    assert '$("next").disabled = step === n && !agree' in q and "privacy: true" in q
    assert "<script src" not in q                                                   # CSP — только хеши своих скриптов


def test_record_doc_append_only(tmp_path):
    path = consents.path_of(tmp_path)
    a = consents.record_doc(path, "form:abc", "privacy", "2026-11-24", "a" * 64, clock=lambda: 5)
    assert consents.record_doc(path, "form:abc", "privacy", "2026-11-24", "a" * 64) == a        # тот же текст — та же
    consents.record_doc(path, "form:abc", "privacy", "2026-11-24", "b" * 64)                    # новый текст — новая
    assert len(consents.listing(path, "form:abc")) == 2 and consents.has_doc(path, "form:abc", "privacy", "2026-11-24")
    assert not consents.has_doc(path, "form:abc", "privacy", "2027-01-01")                      # новая версия — заново
    for bad in (("form:abc", "x", "v", "a" * 64), ("form:abc", "privacy", "", "a" * 64),
                ("form:abc", "privacy", "v", "zz"), ("bad who", "privacy", "v", "a" * 64)):
        with pytest.raises(ValueError):
            consents.record_doc(path, *bad)
    assert consents.public(path, "form:abc")["given"] == []                       # документы — не подключения
