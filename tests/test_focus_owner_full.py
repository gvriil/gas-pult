"""Владелец 21.11: «по фокус-ссылке должны быть все инструменты такие же, как и без неё». Владелец открыл свою
фокус-ссылку там, где вошёл в пульт, — обычная панель на этом чате (все инструменты), устройство не привязывается.
Кто угодно другой — фокус как раньше (права определяет сервер)."""
from pathlib import Path

from test_focus import FX, call, owner, server  # noqa: F401

from gas_pult import focus

HTML = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")


def test_owner_opens_own_link_as_full_panel_without_binding(server):  # noqa: F811
    s = server
    code, d, _ = call(s["base"], "/api/focus/new", {"w": "@1", "base": s["base"]}, owner(s))
    assert code == 200, d
    token = d["url"].split("#focus=")[1]
    code, r, setc = call(s["base"], "/api/focus/open", {"token": token}, owner(s), FX)
    assert code == 200 and r["owner_here"] is True and r["w"] == "@1" and not setc, r   # без cookie фокуса
    rec = next(x for x in s["p"].focus.listing() if x["id"] == d["id"])
    assert not rec.get("devs") and not rec.get("opened"), rec          # слот устройства не занят
    code, r, setc = call(s["base"], "/api/focus/open", {"token": token}, "", FX)   # другой человек — фокус
    assert code == 200 and "owner_here" not in r and setc.startswith(focus.COOKIE + "=")


def test_panel_redirects_owner_and_shows_model_in_focus():
    assert 'if (o?.owner_here) return location.replace(location.pathname + (o.w ? "?session="' in HTML
    assert "body.focus-demo #modeChip, body.focus #mcpChip { display: none !important; }" in HTML
