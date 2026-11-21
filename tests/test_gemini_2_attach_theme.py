"""Gemini 21.11, топ-15 №9 и №11: «Прикрепить» — ПК сразу выбор файла, телефон — Камера / Галерея / Файл (фото
сжимаем сами); тема — переключатель на 3 положения; «Уведомления» — тумблер справа (приём 5: переключатели)."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
PAGE = (WEB / "index.html").read_text(encoding="utf-8")


def test_attach():
    assert '$("plus").onclick = () => split() && !matchMedia("(pointer: coarse)").matches ? $("fFile").click()' in PAGE
    for x in ('label: "Камера"', 'label: "Галерея"', 'label: "Файл"'):
        assert x in PAGE
    assert "Фото без сжатия" not in PAGE and "noShrink" not in PAGE
    assert 'const raw = id === "fFile";' in PAGE


def test_sheet_seg_and_toggle():
    assert "it.seg ? `<div class=\"sseg-row\">" in PAGE and 'data-sv="${v}" role="radio"' in PAGE
    assert "items[+b.dataset.i].run(b.dataset.sv)" in PAGE
    assert 'it.toggle != null ? `<i class="tgl' in PAGE and 'role="switch"' in PAGE


def test_theme_and_push():
    st = (WEB / "js/settings.js").read_text(encoding="utf-8")
    assert 'seg: [["auto", "Система"], ["light", "Светлая"], ["dark", "Тёмная"]], cur: mode' in st
    push = (WEB / "js/push.js").read_text(encoding="utf-8")
    assert '{ label: "На этом устройстве", icon: "bell", toggle: on,' in push
    assert "Включить на этом устройстве" not in push.split("sheet(\"Уведомления\", [", 2)[-1]
