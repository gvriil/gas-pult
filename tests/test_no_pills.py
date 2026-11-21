"""Владелец 20.11: «мы говорили уходить от пилюль, а они всё равно есть». Кнопки, чипы и поля — прямоугольник со
скруглением 8 px (токен), без «пилюль» (скругление ≥ половины высоты). Круглые — только точки и индикаторы."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"


def test_pill_token_is_8px_everywhere():
    for f in ("index.html", "offer.html"):
        assert "--radius-pill: 8px;" in (WEB / f).read_text(encoding="utf-8"), f
    for f in [*WEB.glob("*.html"), *(WEB / "js").glob("*.js")]:
        assert not re.search(r"border-radius:\s*99{2,}px", f.read_text(encoding="utf-8")), f.name


def test_round_icon_buttons_are_rounded_rectangles():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert "  .tool { width: 40px; height: 40px; border-radius: var(--radius-sm);" in page      # «+», микрофон, меню
    vplay = page[page.index("  .vcard .vplay {"):]
    assert "border-radius: 50%" not in vplay[:vplay.index("}")]
