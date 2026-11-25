"""Тема одной кнопкой (владелец 25.11): солнце/луна на каждом экране, помнится на устройстве, по умолчанию — как в
системе; светлая тема контрастнее. Переключение и запоминание проверены Playwright в PR."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "js/themebtn.js").read_text(encoding="utf-8")


def test_part_loaded_and_buttons_in_both_headers():
    assert 'part("themebtn").then((m) => m.init())' in INDEX
    assert '$("settingsBtn")?.before(button("themeTop"))' in JS and '$("sSet")?.before(button("themeSimple"))' in JS
    assert 'store("theme", dark() ? "light" : "dark"); applyTheme();' in JS


def test_light_theme_more_contrast():
    assert "--text-secondary: #374151; --text-muted: #4B5563;" in INDEX and "--border-subtle: #D5D9DF;" in INDEX
