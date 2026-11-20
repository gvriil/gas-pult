"""Владелец 20.11: «пока «Gavriil App» вместо «Пульт» — во всём, что видит человек; сменить потом в одном месте»."""
import json
import re
from pathlib import Path

from gas_pult import brand

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")


def test_one_place_and_manifest():
    assert brand.NAME == "Gavriil App" == brand.DEFAULT
    m = brand.manifest()
    assert m["name"] == m["short_name"] == brand.NAME and m["display"] == "standalone" and m["start_url"] == "/"
    assert '<link rel="manifest" href="/manifest.webmanifest">' in INDEX
    assert f'<meta name="application-name" content="{brand.DEFAULT}">' in INDEX and f"<title>{brand.DEFAULT}</title>" in INDEX


def test_no_visible_pult_in_ui_strings():
    """Видимые строки интерфейса: ни «Пульт» в разметке, ни в строковых литералах (комментарии — можно)."""
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", INDEX, flags=re.S)
    assert not re.search(r'>Пульт<|"Пульт"', code), re.findall(r'.{30}(?:>Пульт<|"Пульт").{10}', code)
    for lang in ("ru", "en"):
        assert json.loads((WEB / f"i18n/{lang}.json").read_text(encoding="utf-8"))["login.brand"] == brand.NAME
