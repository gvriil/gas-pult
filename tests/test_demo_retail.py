"""Сценарий для ритейла /?demo=retail (25.11): часть по требованию, четыре шага, «Да» и «Не отправлять» — разный итог.

Глазами и в браузере: 390 и 1440, светлая и тёмная тема (Playwright в PR). Здесь — что ядро грузит часть только по
ссылке и в сценарии нет кухни разработчика, денег и названия клиента."""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "js" / "retail.js").read_text(encoding="utf-8")


def test_core_loads_part_only_for_retail_link():
    assert 'if (params.get("demo") === "retail") part("retail").then((m) => m.init())' in INDEX
    assert "function play(" not in INDEX                                  # код сценария — не в ядре


def test_four_steps_decision_and_final():
    for x in ("Данные", "Агенты", "Ваше «Да»", "Результат", "Требует решения", "В работе", "Выполнено",
              "Да, отправить покупателю", "Не отправлять", "Без вашего подтверждения ничего не уйдёт",
              "Инструкция компании", "Что измерим в пилоте", "Пройти ещё раз", "Примерить на себя",
              "Полное демо", "Функции пилота", "Концепция пилота · учебные данные", "Моя техника",
              "Открыть инструкцию"):
        assert x in JS, x
    assert 'yes: ["Ответ получен", REPLY]' in JS and 'no: ["Ждёт ответа сотрудника"' in JS  # разный итог
    assert "b.disabled = true" in JS                                       # двойное нажатие не отправит дважды
    assert "55fr" in JS and "45fr" in JS                                   # ПК: поток и макет телефона


def test_font_is_local_part_with_license():
    font = (WEB / "js" / "retailfont.js").read_text(encoding="utf-8")
    assert 'part("retailfont")' in JS and "Open Font License" in font and "data:font/woff2;base64," in font
    assert "U+0400-045F" in font                                           # кириллица


def test_no_dev_kitchen_money_or_client_name():
    text = re.sub(r"//[^\n]*", "", JS.split("const STEPS")[1])          # видимые строки, без комментариев
    for bad in ("$", "₽", "Claude", "Opus", "Sonnet", "dist", "PASS", "лимит", "токен"):
        assert bad not in text.replace("${", "").replace("$r(", "").replace("const $r =", ""), bad
    assert "М.Видео" not in JS and "МВидео" not in JS                     # имя компании — только параметром &to=


def test_company_name_param_is_escaped_and_short():
    assert 'get("to") || "").trim().slice(0, 40)' in JS and "${h(NOTE)}" in JS
