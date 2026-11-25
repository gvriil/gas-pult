"""Название в одном месте (владелец 20.11; 25.11 — «Ладея» / «Ladeya», by Botsmith), «Пульт» в интерфейсе не видно."""
import json
import re
from pathlib import Path

from gas_pult import brand

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")


def test_one_place_and_manifest():
    assert brand.APP_NAME_EN == brand.NAME == "Ladeya"
    assert brand.APP_NAME_RU == brand.NAME_RU == "Ладея" == brand.DEFAULT
    m = brand.manifest()
    assert m["name"] == m["short_name"] == brand.NAME_RU and m["display"] == "standalone" and m["start_url"] == "/"
    assert '<link rel="manifest" href="/manifest.webmanifest">' in INDEX
    assert f'<meta name="application-name" content="{brand.DEFAULT}">' in INDEX
    assert f"<title>{brand.DEFAULT}</title>" in INDEX


def test_no_visible_pult_in_ui_strings():
    """Видимые строки интерфейса: ни «Пульт» в разметке, ни в строковых литералах (комментарии — можно)."""
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", INDEX, flags=re.S)
    assert not re.search(r'>Пульт<|"Пульт"', code), re.findall(r'.{30}(?:>Пульт<|"Пульт").{10}', code)
    for lang in ("ru", "en"):
        want = brand.NAME_RU if lang == "ru" else brand.NAME
        assert json.loads((WEB / f"i18n/{lang}.json").read_text(encoding="utf-8"))["login.brand"] == want


def test_focus_manifest_opens_focus():
    """Владелец 22.11: фокус-ссылка на экране «Домой» открывает фокус, а не вход в пульт."""
    m = brand.manifest(focus=True)
    assert m["start_url"] == m["id"] == "/?focus" and m["scope"] == "/" and "share_target" not in m
    assert brand.manifest()["start_url"] == "/"
    assert '"/manifest.webmanifest?focus"' in INDEX and 'if (FOCUS) document.querySelector' in INDEX


def test_old_home_icon_redirects_to_focus():
    """Старый значок открывает «/»: ответ focus_scope ведёт в фокус (скриншот владельца 22.11)."""
    assert 'err.code === "focus_scope" && !FOCUS && !SLINK) { location.replace("/?focus")' in INDEX
