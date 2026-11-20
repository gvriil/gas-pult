"""Карта навигации 19.11, шаг 1: секции панели сворачиваются и запоминаются, «Свернуть всё», «Настройки» внизу."""
from pathlib import Path

INDEX = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")


def test_sections_fold_and_remember():
    for k, t in (("pins", "Закреплённые"), ("proj", "Проекты"), ("chats", "Чаты")):
        assert f'fold("{k}", "{t}")' in INDEX
    assert 'sec("Недавние")' not in INDEX                     # одно слово «чат» везде
    assert 'store("navShut"' in INDEX and 'navSet("navShut")' in INDEX
    assert "const shut = (k) => !q && NAV.shut.has(k);" in INDEX   # при поиске свёрнутое не прячет найденное


def test_fold_all_and_settings_at_bottom():
    assert 'id="navFoldBtn"' in INDEX and '"Развернуть всё" : "Свернуть всё"' in INDEX
    assert '<button class="nav-foot" id="navSet" type="button"></button>\n</aside>' in INDEX
    assert '$("navSet").onclick = () => { navOpen(false); $("settingsBtn").click(); };' in INDEX


def test_review_fixes():
    """Слепая проверка #340: фокус-режим, касание 44 px, фокус клавиатуры после свёртки, «всё свёрнуто» без «Закреплённых»."""
    assert "body.focus #navSet { display: none !important; }" in INDEX
    assert '$("settingsBtn").hidden = $("navSet").hidden = gate;' in INDEX
    assert "@media (pointer: coarse) { .nav-sec.fold { min-height: 44px; }" in INDEX
    assert "querySelector(`[data-nsec=${k}]`)?.focus()" in INDEX
    assert 'querySelectorAll("[data-nsec]")].every(' in INDEX
