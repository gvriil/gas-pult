"""Штаб 21.11, пункт 3: «Ubuntu» → «Браузер» везде, где видит человек (кнопка наверху, ссылки, настройки, помощь)."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"


def visible(text: str) -> str:
    """Без комментариев: // … до конца строки и /* … */."""
    return re.sub(r"/\*.*?\*/", "", re.sub(r"(?m)//.*$", "", text), flags=re.S)


def test_no_ubuntu_for_people():
    for f in [WEB / "index.html", *(WEB / "js").glob("*.js")]:
        assert "Ubuntu" not in visible(f.read_text(encoding="utf-8")), f.name
    help_ = (Path(__file__).resolve().parents[1] / "src/gas_pult/help/screens.toml").read_text(encoding="utf-8")
    assert "Ubuntu" not in "\n".join(x for x in help_.splitlines() if not x.lstrip().startswith("#"))


def test_browser_words():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<span class="lbl">Браузер</span>' in page and 'label: "Открыть в Браузере"' in page
    assert "<span>В Браузере<small>" in (WEB / "js/links.js").read_text(encoding="utf-8")


def test_desk_resizes_and_utf8_clipboard():
    """Стол на Xvnc (штаб 21.11): «вписать» — стол того же размера, что окно (resizeSession); буфер UTF-8 — русский
    текст вставляется как есть, клавишами — только для старого сервера (Latin-1). Проверено вживую: 390×844 и 1440×900,
    «Привет, стол — проверка ёЁ» туда и «Ответ со стола — щука» обратно."""
    js = (WEB / "js/desktop.js").read_text(encoding="utf-8")
    assert "rfb.scaleViewport = false; rfb.resizeSession = true;" in js
    assert "fit() { rfb.clipViewport = false; rfb.scaleViewport = narrow(); rfb.resizeSession = true; }" in js
    assert "get utf8() { return !!rfb._clipboardServerCapabilitiesFormats?.[1]; }" in js
    assert "const wide = /[^\\u0000-\\u00ff]/.test(text) && !deskScr.utf8" in js
