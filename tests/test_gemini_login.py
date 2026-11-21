"""Gemini 21.11, топ-15 №5: вход — не «стена из 8 кнопок». Одна главная кнопка (Telegram), Face ID — второй; Google,
Яндекс, Почта — одним рядом; «Есть код приглашения?», «Демо без входа», «Вход для администратора» — ссылками внизу.
Идентификаторы кнопок прежние — обработчики и сервер не меняются."""
import json
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
PAGE = (WEB / "index.html").read_text(encoding="utf-8")


def test_layout():
    step = PAGE[PAGE.index('<div id="loginStep1">'):PAGE.index('<div id="loginStep2"')]
    assert step.count('class="btn"') == 1                                   # одна главная
    row = step[step.index('<div class="oa-row">'):]
    row = row[:row.index("</div>")]
    for x in ('id="googleLogin"', 'id="yandexLogin"', 'id="emailLogin"'):
        assert x in row
    links = step[step.index('<div class="login-links">'):]
    for x in ('class="linkbtn" id="invCodeBtn"', 'class="linkbtn" id="tryDemo"', 'class="linkbtn small" id="getCode"'):
        assert x in links
    assert 'data-l="login.title">Вход</h2>' in PAGE


def test_words_short_both_languages():
    ru = json.loads((WEB / "i18n/ru.json").read_text(encoding="utf-8"))
    en = json.loads((WEB / "i18n/en.json").read_text(encoding="utf-8"))
    assert (ru["login.google"], ru["login.yandex"], ru["login.email"]) == ("Google", "Яндекс", "Почта")
    assert (en["login.google"], en["login.yandex"], en["login.email"]) == ("Google", "Yandex", "Email")
    assert ru["login.code"] == "Вход для администратора" and en["login.code"] == "Admin sign-in"
    assert ru["login.title"] == "Вход" and en["login.title"] == "Sign in"
