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
    for s in ("Данные входят", "Агенты работают", "Вы решаете", "Результат", "Требует решения", "В работе", "Выполнено",
              "Да, отправить", "Не отправлять", "Без вашего подтверждения ничего не уйдёт",
              "Показать инструкцию компании",
              "Что измерим в пилоте", "Пройти ещё раз", "Примерить на себя", "Полное демо", "функции пилота",
              "Концепция пилота · учебные данные"):
        assert s in JS, s
    assert '"ответ получен" : "ждёт ответа сотрудника"' in JS              # «Да» и «Нет» — разный итог


def test_no_dev_kitchen_money_or_client_name():
    text = re.sub(r"//[^\n]*", "", JS.split("const ICON")[1])          # видимые строки, без комментариев
    for bad in ("$", "₽", "Claude", "Opus", "Sonnet", "dist", "PASS", "лимит", "токен"):
        assert bad not in text.replace("${", ""), bad
    assert "М.Видео" not in JS and "МВидео" not in JS                     # имя компании — только параметром &to=


def test_company_name_param_is_escaped_and_short():
    assert 'get("to") || "").trim().slice(0, 40)' in JS and "${to ? h(to) :" in JS
