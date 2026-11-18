"""Роутер моделей и кэш повторов (GAS-16, слой 6): тип задачи → подсказка модели по routing.md штаба; тот же длинный
вопрос в ту же сессию за 10 минут — предупреждение, повтор после него — уходит."""

import pytest

from gas_pult import router

ALL = {"claude", "openrouter"}


@pytest.mark.parametrize("text,kind,model", [
    ("Зайди на сайт поставщика и выгрузи прайс", "browser", "haiku"),
    ("Почему не работает оплата на сайте? Разберись", "explore", "sonnet"),
    ("Поправь баг в функции расчёта и добавь тест", "code", "sonnet"),
    ("Сделай краткую сводку по протоколу встречи", "text", "haiku"),
    ("Возьми таблицу с Google Диска и посчитай итоги", "google", "haiku"),
])
def test_classify_and_route(text, kind, model):
    r = router.route(text, ALL)
    assert r["type"] == kind and r["profile"] == "claude" and r["model"] == model and r["why"]


def test_fallback_and_limited_use():
    r = router.route("Зайди на сайт и заполни форму", {"openrouter"})          # Anthropic не готов — запасная
    assert r["profile"] == "openrouter" and r["model"] == "xiaomi/mimo-v2.6-flash"
    assert router.route("Данные из Google Диска — в отчёт", {"openrouter"}) is None   # Limited Use: без запасной
    assert router.route("Привет, как дела?", ALL) is None                      # тип не понятен — без подсказки
    assert router.route("Зайди на сайт", ALL)["fallback"]["model"] == "xiaomi/mimo-v2.6-flash"


def test_valid_model():
    assert router.valid_model("deepseek/deepseek-v4-flash-0731") and router.valid_model("") == ""
    with pytest.raises(ValueError):
        router.valid_model("haiku; rm -rf ~")


def test_repeat_cache():
    rp, q = router.Repeat(), "Посчитай выручку за ноябрь по всем магазинам и пришли таблицу"
    assert rp.check("@1", q, now=0) is None
    rp.done("@1", q, now=0)
    assert rp.check("@1", q, now=120) == 120                                   # тот же вопрос через 2 мин — стоп
    assert rp.check("@1", q, now=150) is None                                  # повтор после предупреждения — уходит
    rp.done("@1", q, now=150)
    assert rp.check("@2", q, now=160) is None                                  # другая сессия — можно
    assert rp.check("@1", "  " + q.upper() + " ", now=200) == 50               # регистр и пробелы — тот же вопрос
    assert rp.check("@1", q, now=150 + 11 * 60) is None                        # через 10 минут — можно
    rp.done("@1", "да", now=0)
    assert rp.check("@1", "да", now=1) is None                                 # короткие — не трогаем
