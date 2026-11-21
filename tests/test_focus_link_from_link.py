"""Штаб 21.11, пункт 5: из фокус-ссылки — ещё одна (на тот же чат, его проект или чат проекта); значки различают
чат и проект. Список — часть js/focuslinks.js; заголовок новой ссылки — название чата, не имя окна tmux."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
JS = (WEB / "js/focuslinks.js").read_text(encoding="utf-8")


def test_icons_and_card():
    assert 'icon: x.mode === "demo" ? "eye" : x.proj ? "folder" : "chat",' in JS
    assert "run: () => card(x) }))]" in JS
    card = JS[JS.index("function card(x)"):]
    for s in ('"Новая ссылка на этот проект"', '"Новая ссылка на этот чат"', '"Ссылка на проект «"',
              '{ head: "Ссылка на один чат проекта" }', '"Отозвать эту ссылку"'):
        assert s in card, s


def test_core_moved_and_title():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'const focusList = () => part("focuslinks").then((m) => m.open());' in page
    assert "async function focusList()" not in page
    assert "projOf(proj)?.name || d.name" in page
