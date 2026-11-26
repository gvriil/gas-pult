"""Права до подключения (штаб 26.11, аудит Atoms п. 3): на экране согласия — куда идут данные и что понадобится, только
из каталога пульта (mcp.PRESETS: url, fields) — без выдуманных сведений."""
from pathlib import Path

from gas_pult import mcp

JS = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/js/connections.js").read_text(encoding="utf-8")


def test_rights_from_catalog_only():
    assert "function facts(it)" in JS and "${facts(it)}" in JS
    assert "new URL(p.url).host" in JS and "p.fields" in JS
    for k in ("Куда идут данные", "Что понадобится", "Где работает"):
        assert k in JS


def test_catalog_has_the_facts():
    for p in mcp.PRESETS:                                   # у каждого шаблона — либо адрес, либо свой сервер пульта
        assert p.get("url") or p.get("type") in ("builtin", "stdio"), p["id"]
        assert isinstance(p.get("fields", []), list)
