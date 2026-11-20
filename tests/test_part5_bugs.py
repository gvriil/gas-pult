"""Баги из разбора Gemini 20.11 (часть 5): иконка «Шагов», терминал во всю высоту, шапка телефона, плашка поставщика."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
INDEX = (WEB / "index.html").read_text(encoding="utf-8")


def test_every_used_icon_exists():
    """«Шаги» были с icon: "list", а такой иконки нет — пункт без значка. Каждая иконка кода — в наборе."""
    table = INDEX[INDEX.index("const P = {\n"):]
    table = table[:table.index("\n};")]
    defined = set(re.findall(r"\b([a-z][a-z0-9]*): '<", table))
    srcs = [INDEX] + [p.read_text(encoding="utf-8") for p in (WEB / "js").glob("*.js")]
    used = {m for src in srcs for m in re.findall(r'(?:ic\(|icon: )"([a-z0-9]+)"', src)}
    assert used - defined == set(), used - defined


def test_terminal_fills_height_and_phone_header():
    assert "min-height: calc(var(--app-h, 100dvh) - 320px); }" in INDEX
    assert ".term pre { margin-top: auto !important; }" in INDEX
    assert "@media (max-width: 480px) { .top .hpill span { display: none; }" in INDEX


def test_provider_gap_bar_shown_once():
    a = INDEX.index("function paintGaps(s) {")
    body = INDEX[a:INDEX.index("function gapsView(", a)]
    assert 'seen === "seen" && el?.dataset.s !== s.id' in body and 'store("gaps:" + p.id, "seen")' in body
