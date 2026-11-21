"""Gemini 21.11, топ-15 №7: три режима «Быстро / Обычно / Глубоко» для всех, «Точнее…» — модель и усилие; модель и
шесть усилий — в режиме разработчика. Штаб 21.11, вариант А: режим = усилие на текущей модели (словарь MODES)."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"


def test_modes_in_one_place():
    js = (WEB / "js/picker.js").read_text(encoding="utf-8")
    assert 'export const MODES = [["low", "Быстро",' in js
    assert '["medium", "Обычно",' in js and '["high", "Глубоко",' in js
    assert js.count('", ""]') >= 3                                        # модель режима пустая — вариант А
    assert "if (!full && !dev() && hasEffort(profile, sel) && !differ) return openModes(s, profile, sel, cur);" in js
    assert '{ label: "Точнее…", icon: "settings", sub: "модель и усилие", run: () => open(s, true) }' in js


def test_labels_in_new_chat_and_chat_row():
    nc = (WEB / "js/newchat.js").read_text(encoding="utf-8")
    assert 'const MODE_T = { low: "Быстро", medium: "Обычно", high: "Глубоко" }' in nc
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert '["Быстро", "Обычно", "Глубоко"][k]' in page
    assert 'mode = !dev() && (s?.harness || "claude") === "claude"' in page
