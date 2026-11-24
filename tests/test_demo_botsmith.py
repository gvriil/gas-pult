"""Демо из QR и вход гостя — бренд Botsmith (владелец 24.11: «и из демо тоже… поставь botsmith»), строка под логотипом
— «Операционная система бизнеса на ИИ-агентах». Панель на «/» без demo — прежняя («Гаврила»)."""
import urllib.request

from test_people_login import server  # noqa: F401

from gas_pult import brand


def get(base, path):
    with urllib.request.urlopen(base + path) as r:
        return r.read().decode("utf-8"), dict(r.headers)


def test_variant_page(server):  # noqa: F811
    _, base = server
    plain, h1 = get(base, "/")
    demo, h2 = get(base, "/?demo")
    guest, _ = get(base, "/?brand=botsmith")
    assert "Гаврила" in plain and "Botsmith" not in plain
    for page in (demo, guest):
        assert "Гаврил" not in page and "Gavrila" not in page and "<title>Botsmith</title>" in page
        assert brand.BS_TAGLINE in page and "/brand/botsmith-icon.svg" in page and "?brand=botsmith" in page
    assert h1["ETag"] != h2["ETag"]                       # варианты не путаются в кэше браузера
    icon, h = get(base, "/brand/botsmith-icon.svg")
    assert icon.startswith("<svg") and h["Content-Type"].startswith("image/svg")


def test_parts_branded_on_request(server):  # noqa: F811
    _, base = server
    plain, _ = get(base, "/js/settings.js")
    bs, _ = get(base, "/js/settings.js?brand=botsmith")
    assert "Гаврил" in plain and "Гаврил" not in bs and "Botsmith" in bs
