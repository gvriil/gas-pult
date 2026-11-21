"""Gemini 21.11, топ-15 №2: «4 квадрата» убрать; режим и интеграции — в строку поля ввода, как в «Новом чате»;
«Команды» — разработчику, в «⋯» чата. В фокус-ссылке и у тестировщика меню остаётся (там «Завершить», «Позвать»)."""
from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")


def test_layout():
    assert "body:not(.focus):not(.tester) #menuBtn { display: none !important; }" in PAGE
    assert '<button class="dchip mode" id="modeChip" type="button"' in PAGE and 'id="mcpChip"' in PAGE
    assert '$("modeChip").onclick = () => ACTIONS.models();' in PAGE
    assert '$("mcpChip").onclick = () => ACTIONS.chatmcp();' in PAGE
    assert "body:not(.split):not(.focus) #target { display: none; }" in PAGE


def test_commands_for_developer():
    assert '...(dev() && meta?.role !== "viewer" && !FOCUS ? [{ label: "Команды Claude", icon: "bolt"' in PAGE
