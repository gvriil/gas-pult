"""Gemini 21.11, топ-15 №8: «⋯» панели — только разработчику; «Сегодня» (брифинг) и «Задачи» — строками в панели под
«Новый чат», как Inbox в Linear; «Пригласить человека» — в «Настройках». Полоса наверху — без «Брифинг» и «Задачи»."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
PAGE = (WEB / "index.html").read_text(encoding="utf-8")


def test_nav_rows_and_menu():
    assert 'id="navToday" type="button" hidden' in PAGE and 'id="navTasks" type="button" hidden' in PAGE
    assert 'body.nocap-dev_terminal #navMoreBtn { display: none !important; }' in PAGE
    assert '$("navToday").onclick = () => { navOpen(false); briefGo(); };' in PAGE
    assert ('$("spaces").querySelector(".sp-brief").hidden = $("spaces").querySelector(".sp-tasks").hidden = true;'
            in PAGE)


def test_invite_in_settings():
    st = (WEB / "js/settings.js").read_text(encoding="utf-8")
    assert '{ label: "Пригласить человека", icon: "mail", sub: "ссылка-приглашение в пульт", run: spaceInvite }' in st
