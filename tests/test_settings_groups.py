"""Карта навигации 19.11, шаг 2: настройки по группам, код — в части js/settings.js (ядро освобождено)."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
SET = (WEB / "js/settings.js").read_text(encoding="utf-8")


def test_settings_are_a_lazy_part():
    assert 'part("settings").then((m) => m.open())' in INDEX
    assert "const legend = () => part(\"settings\").then((m) => m.legend());" in INDEX
    assert 'sheet("Настройки", [' not in INDEX and "function legend()" not in INDEX


def test_groups_in_order_and_nothing_lost():
    titles = re.findall(r'\{ title: "([^"]+)"', SET)
    assert titles == ["Внешний вид", "Интеграции", "Модели и расход", "Люди и доступ", "Вход и безопасность",
                      "Уведомления и брифинг", "Помощь и данные"]
    for label in ("Как в системе", "Размер текста", "Анкеты клиентов", "Ключи входа — Face ID", "Способы входа",
                  "Ссылки: где открывать", "Компьютеры — ваш браузер", "Брифинг: источники и время",
                  "Почта для входа и оповещений", '"Страна"', "Уведомления", "Проверка", 'T("st.title")', '"Люди"',
                  '"Команда"', "Корзина чатов", "Фокус-ссылки", "Модель по умолчанию", "Расход и лимиты",
                  'T("caps.title")', '"Язык: "', "Обозначения", "Пройти тур", "Перезагрузить панель",
                  "Выйти на этом устройстве", 'go("go:integrations")'):
        assert label in SET, label
    assert ".filter((g) => g.items.some((x) => !x.head))" in SET           # пустая для роли группа не показывается


def test_role_conditions_kept():
    """Слепая проверка #341: условия показа — те же, что в прежнем плоском списке (перенос строк без правок)."""
    for cond, label in (('meta?.role === "owner" && !FOCUS', "Анкеты клиентов"),
                        ('meta?.space && meta?.role !== "owner"', 'T("dev.title")'),
                        ("deskLinks()", "Ссылки: где открывать"), ('meta?.role === "owner"', "Компьютеры"),
                        ('meta?.role === "owner"', "Брифинг"), ("canNotify()", '"Уведомления"'),
                        ('meta?.role === "owner"', '"Проверка"'), ('meta?.role === "owner"', 'T("st.title")'),
                        ("isBoss()", '"Люди"'), ('meta?.role === "owner" && UI?.can_team', '"Команда"'),
                        ('meta?.role === "owner"', "Корзина чатов"), ('meta?.role === "owner"', "Фокус-ссылки"),
                        ('meta?.role === "owner"', "Модель по умолчанию"),
                        ('meta?.role !== "viewer"', "Расход и лимиты"),
                        ("UI", 'T("caps.title")'), ('meta?.via === "browser"', "Выйти на этом устройстве"),
                        ("tgBig()", "Во весь экран")):
        line = next(x for x in SET.splitlines() if label in x)
        assert f"...({cond} ? [" in line, (label, line[:100])
