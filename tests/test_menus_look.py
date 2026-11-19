"""Меню и шторки (владелец 19.11: «поаккуратней эти менюшки… белый дизайн»): на ПК шторка — окно по центру,
пункты без значка — на одной линии, касанием — ≥ 44 px."""

from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")


def test_sheet_is_dialog_on_desktop_and_aligned():
    assert "@media (min-width: 900px) {\n    .sheet-bg { align-items: center; justify-content: center;" in PAGE
    assert ".sheet { width: min(480px, 100%);" in PAGE and "animation: popin .14s ease" in PAGE
    assert ".sheet button[data-i]:not(:has(> .i:first-child, > .sdot, > .vis)) { padding-left: 48px; }" in PAGE
    assert "@media (pointer: coarse) { .pop button { min-height: 44px; } }" in PAGE
