"""Озвучка: ссылки не читаем («ссылка»), числа — словами по-русски, латиница — русскими буквами (Silero её пропускает).
Одна кнопка «Прослушать» и скорость 1×–2× в плеере; скорость — в настройках человека на сервере."""

import json
from pathlib import Path

import pytest

from gas_pult import transcripts, voice, webapp
from gas_pult.config import Config
from gas_pult.speech import cardinal, decimal, ordinal, speakable

PAGE = (Path(webapp.__file__).parent / "web" / "index.html").read_text(encoding="utf-8")


# ---------- ссылки и пути ----------
@pytest.mark.parametrize("src, want, gone", [
    ("Смотри [PR #153](https://github.com/o/r/pull/153).", "пи-ар номер сто пятьдесят три", "github"),
    ("Открой https://example.org/a?b=1 и www.example.com/x", "ссылка и ссылка", "example"),
    ("Подробно: [https://example.org](https://example.org)", "ссылка", "example"),
    ("Пиши на bot@example.com", "адрес почты", "@"),
    ("Сайт example.ru открыт", "Сайт ссылка открыт", "example"),
    ("Правка в ~/projects/app/src/webapp.py:2149", "файл вебапп, строка две тысячи сто сорок девять", "/"),
    ("Смотри webapp.py:12 и README.md", "файл вебапп, строка двенадцать и файл ридми", "."),
    ("Папка src/gas_pult/web/ готова", "Папка веб готова", "src"),
    ("Файл /etc/x/config.toml", "Файл конфиг", "файл файл"),
])
def test_links_and_paths(src, want, gone):
    out = speakable(src)
    assert want in out, out
    assert gone not in out.lower(), out


def test_slash_words_are_not_paths():
    assert speakable("и/или") == "и/или"


def test_clean_uses_links():
    out = transcripts.clean("**Готово**: [док](https://x.y), путь `~/a/b/run.sh`, адрес https://a.b/c")
    assert "док" in out and "файл run" in out and "https" not in out and "~/" not in out


# ---------- числа ----------
@pytest.mark.parametrize("n, fem, want", [
    (0, False, "ноль"), (1, False, "один"), (1, True, "одна"), (2, True, "две"), (11, False, "одиннадцать"),
    (21, True, "двадцать одна"), (105, False, "сто пять"), (1000, False, "тысяча"),
    (1234, False, "тысяча двести тридцать четыре"), (2000, False, "две тысячи"), (21000, False, "двадцать одна тысяча"),
    (1_000_000, False, "один миллион"), (-5, False, "минус пять"),
])
def test_cardinal(n, fem, want):
    assert cardinal(n, fem) == want


@pytest.mark.parametrize("n, end, want", [
    (1, "й", "первый"), (2, "й", "второй"), (3, "е", "третье"), (3, "го", "третьего"), (9, "е", "девятое"),
    (23, "го", "двадцать третьего"), (40, "й", "сороковой"), (2026, "го", "две тысячи двадцать шестого"),
    (2000, "го", "двухтысячного"), (100, "й", "сотый"),
])
def test_ordinal(n, end, want):
    assert ordinal(n, end) == want


def test_decimal():
    assert decimal("1", "5") == "одна целая пять десятых"
    assert decimal("3", "14") == "три целых четырнадцать сотых"
    assert decimal("0", "01") == "ноль целых одна сотая"


@pytest.mark.parametrize("src, want", [
    ("Готово за 5 минут", "Готово за пять минут"),
    ("Осталась 21 минута, 2 недели и 1 строка", "Осталась двадцать одна минута, две недели и одна строка"),
    ("через 2 часа, 3 дня", "через два часа, три дня"),
    ("через 5 дн., 1 ч и 3 мин", "через пять дней, один час и три минуты"),
    ("Загрузка 45%", "Загрузка сорок пять процентов"),
    ("Рост 2,5%", "Рост две целых пять десятых процента"),
    ("Файл 1,5 ГБ", "Файл одна целая пять десятых гигабайта"),
    ("Срок 09.11", "Срок девятое ноября"),
    ("Вход до 09.11", "Вход до девятого ноября"),
    ("Отчёт 12.11.2026", "Отчёт двенадцатое ноября две тысячи двадцать шестого года"),
    ("в 2026 году", "в две тысячи двадцать шестом году"),
    ("В 19:00 и в 9:05", "В девятнадцать ноль-ноль и в девять ноль пять"),
    ("с 1-го числа, 5-й раз", "с первого числа, пятый раз"),
    ("версия 1.2.3", "версия один точка два точка три"),
    ("Строк 1 000 000", "Строк один миллион"),
    ("Пи 3.14", "Пи три целых четырнадцать сотых"),
    ("за 56.7s", "за пятьдесят шесть целых семь десятых секунды"),
    ("коммит a6345b1b", "коммит хеш"),
])
def test_numbers_in_text(src, want):
    assert speakable(src) == want


# ---------- латиница ----------
@pytest.mark.parametrize("src, want", [
    ("Claude Code на GitHub", "клод код на гитхаб"),
    ("PR слит, CI зелёный, e2e прошли", "пи-ар слит, си-ай зелёный, и-ту-и прошли"),
    ("ElevenLabs и Silero", "элевен лабс и силеро"),
    ("Запустил pytest и ruff", "Запустил пайтест и рафф"),
    ("Модель GLM от OpenRouter", "Модель джи-эл-эм от опенроутер"),
    ("Протокол XYZ", "Протокол икс-уай-зед"),
    ("Frontend", "фронтенд"),
])
def test_latin_is_spoken(src, want):
    assert speakable(src) == want


def test_no_latin_or_digits_left_for_silero():
    text = ("Сделал PR #154 в GitHub: 3 файла, 120 строк, тесты 58 из 58 за 2.5 минуты. "
            "Смотри https://github.com/o/r/pull/154 и ~/w/src/speech.py:10. Claude Code v2 на Ubuntu 24.04.")
    out = speakable(text)
    assert not any(c.isdigit() for c in out), out
    assert not any("a" <= c.lower() <= "z" for c in out), out


def test_elevenlabs_keeps_latin_but_not_links():
    out = speakable("Claude на GitHub: https://github.com/x, 3 файла", latin_ok=True)
    assert "Claude" in out and "GitHub" in out and "ссылка" in out and "три файла" in out and "https" not in out


def test_tts_speaks_words(monkeypatch):
    """/api/tts: в синтез уходит текст без цифр и латиницы (локальный голос)."""
    p = webapp.Panel(Config(token="1:T", owners=[1]))
    said = []
    monkeypatch.setattr(p, "message", lambda w, i: "Готово: 5 тестов на GitHub, [PR](https://github.com/x).")
    monkeypatch.setattr(p, "voice", lambda personal=False: "irina")
    monkeypatch.setattr(voice, "synth", lambda v, text, out, timeout=300: said.append(text) or out.write_bytes(b"mp3"))
    assert p.tts({"id": "@1"}, full=True) == b"mp3"
    assert said == ["Готово: пять тестов на гитхаб, пи-ар."]


# ---------- панель: одна кнопка, скорость ----------
def test_one_listen_button():
    assert "data-sayfull" not in PAGE and "Целиком</button>" not in PAGE and ">Кратко<" not in PAGE
    assert 'Прослушать</button>' in PAGE and '["say", "vol", "Прослушать"]' in PAGE
    assert "const RATES = [1, 1.25, 1.5, 2];" in PAGE and "data-vrate" in PAGE
    assert "p.playbackRate = p.defaultPlaybackRate = voiceRate();" in PAGE


def test_rate_pref_saved(tmp_path):
    from gas_pult import people
    pp = people.People(tmp_path / "people.json", owners=[1])
    assert pp.prefs(7)["rate"] == 1.0
    assert pp.set_prefs(7, rate=1.5)["rate"] == 1.5
    assert pp.prefs(7)["rate"] == 1.5 and pp.prefs(7)["lang"] == "ru"
    pp.set_prefs(7, lang="en")
    assert pp.prefs(7)["rate"] == 1.5                       # другая настройка скорость не сбрасывает
    with pytest.raises(ValueError):
        pp.set_prefs(7, rate=3)


def test_rate_via_api(monkeypatch, tmp_path):
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    from gas_pult import webauth
    monkeypatch.setenv("GAS_PULT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("GAS_PULT_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    p = webapp.Panel(Config(token="1:T", owners=[7001], region="NL"))
    p.people.add(7002, "member", "Тест")
    p.people.accept(7002)
    p.people.set_country(7002, chosen="NL")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), webapp.handler(p))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base, tok = f"http://127.0.0.1:{srv.server_address[1]}", p.auth.issue(7002)

    def call(path, body=None):
        req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                     {"Cookie": f"{webauth.COOKIE}={tok}"})
        try:
            r = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            r = e
        return (r.status if hasattr(r, "status") else r.code), json.loads(r.read() or b"{}")

    try:
        assert call("/api/prefs", {"rate": 1.25})[1]["rate"] == 1.25
        assert call("/api/meta")[1]["prefs"]["rate"] == 1.25
        assert call("/api/prefs", {"rate": 5})[0] == 400
        assert call("/api/prefs", {"rate": "2"})[0] == 400
        assert call("/api/prefs", {"lang": "en"})[1]["rate"] == 1.25
    finally:
        srv.shutdown()
