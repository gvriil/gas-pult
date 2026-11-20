"""«Быстрые функции» у поля ввода (разбор Gemini, таблица отладочного; «да» владельца 20.11): без дублей с «⋯»."""
from pathlib import Path

INDEX = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")


def test_menu_has_only_quick_functions():
    a = INDEX.index('$("menu").innerHTML = ')
    menu = INDEX[a:INDEX.index("\n}\n", a)]
    for gone in ('"say"', '"active"', '"refresh"', '"switch"'):
        assert gone not in menu, gone
    assert '["models", "chip", "Модель и усилие"]' in menu and '["commands", "bolt", "Команды"]' in menu
    assert 'data-act="chatmcp" data-owner' in menu
    assert 'data-act="close" class="danger focus-only"' in menu                 # «Завершить» — только в фокусе
    assert "chatmcp: () =>" in INDEX
