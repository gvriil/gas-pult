"""Владелец 20.11: «многие вещи не должны быть на виду».

Видно два состояния — «работает» и «ждёт ответа»; модель, папка, ветка, контекст, расход, поставщик,
«активная в чате» — в «⋯ → Подробнее».
"""
from pathlib import Path

INDEX = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/index.html").read_text(encoding="utf-8")


def fn(name):
    a = INDEX.index(name)
    return INDEX[a:INDEX.index("\nfunction ", a + 1)]


def test_card_shows_only_human_things():
    c = fn("function card(s, chat) {")
    for tech in ("folder(s.path)", "s.branch", "s.model", "provChip(s)", "активная в чате", "ctxMeter(s)",
                 "reposLine(s)", 'T("ago.stale")'):
        assert tech not in c, tech
    assert "${costNear(s) ? costChip(s) : \"\"}" in c                         # расход — только у лимита
    assert "${loud(s) ? `<span class=\"chip ${st.cls}\">${st.label}</span>` : \"\"}" in c and "ctxWarn(s)" in c


def test_header_and_input_line_quiet():
    p = fn("function paintSession(s) {")
    assert "folder(s.path)" not in p and "provChip(s)" not in p and "контекст " not in p
    i = fn("function sinfo(s) {")
    assert "[ctxWarn(s), lim ? limitsLine(limitsInfo) : \"\"]" in i
    assert "const loud = (s) => s?.status === \"busy\" || s?.status === \"dialog\";" in INDEX


def test_details_sheet_has_everything():
    d = fn("function chatDetails(id) {")
    for k in ("Модель", "Поставщик", "Контекст", "Расход", "Папка", "Ветка", "Репозитории", "В чате бота",
              "Экран терминала"):
        assert f'"{k}"' in d, k
    assert 'label: "Показать подробности", icon: "eye"' in INDEX
    assert 'label: "Открыть", icon: "chat", run: () => openSession(id)' not in INDEX
