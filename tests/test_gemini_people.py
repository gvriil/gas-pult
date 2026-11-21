"""Gemini 21.11, топ-15 №12: «Люди» и «Команда» — один пункт «Команда и права»; в списке — имя, роль, когда входил;
ID, @имя, страна, IP, устройство, условия — в карточке человека (владельцу или в режиме разработчика)."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
JS = (WEB / "js/people.js").read_text(encoding="utf-8")


def test_list_quiet():
    lst = JS[JS.index("export async function peopleSheet()"):JS.index("const personDetails")]
    assert 'sheet("Команда и права", [' in lst
    assert "countryLine" not in lst and "p.username ? \" · @\"" not in lst and "Страна по IP" not in lst
    assert '"Без имени"' in lst and "«ID " not in lst
    assert 'label: "Что видят сотрудники"' in lst


def test_details_in_card():
    card = JS[JS.index("export function personSheet(p)"):]
    assert '...(owner || dev() ? [{ info: true, icon: "place", label: "ID " + p.id, sub: personDetails(p)' in card
    assert "Страна по IP" in card


def test_settings_one_item():
    st = (WEB / "js/settings.js").read_text(encoding="utf-8")
    assert '{ label: "Команда и права", icon: "place"' in st
    assert 'label: "Люди"' not in st and 'label: "Команда", icon' not in st
