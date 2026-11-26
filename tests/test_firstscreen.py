"""Первый экран простого режима (штаб 26.11, аудит Atoms п. 1): у пустого чата — «Что поручим сегодня?», три задачи
и «Для себя · Для бизнеса». Задача — одно нажатие (текст в поле), отправка — второе. Владельцу — только по флагу.
Проверка по исходникам; вживую — демо /?demo&simple=1&first (снимки — в PR)."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
FS = (WEB / "js" / "firstscreen.js").read_text(encoding="utf-8")
CORE = (WEB / "index.html").read_text(encoding="utf-8")


def test_three_tasks_two_modes_ru_en():
    for s in ("Что поручим сегодня?", "Для себя", "Для бизнеса", "Разобрать почту", "Спланировать день",
              "Подготовить отчёт", "What shall we do today?"):
        assert s in FS
    assert FS.count('["Разобрать почту"') == 2 and FS.count('["Sort my email"') == 2   # оба режима, оба языка


def test_two_taps_nothing_sent_by_itself():
    assert "t.value = " in FS and "t.focus()" in FS          # задача только встаёт в поле
    assert "api(" not in FS and "fetch(" not in FS and "sSend" not in FS


def test_owner_untouched_viewer_never():
    assert 'role !== "viewer"' in FS and 'store("firstScreen") === "1"' in FS and 'role !== "owner"' in FS


def test_core_hook_small_and_nothing_removed():
    assert '<div id="sFirst" hidden></div>' in CORE and 'part("firstscreen")' in CORE
    assert 'T("s.empty")' in CORE                              # прежняя строка пустого чата осталась
    assert len(CORE.encode("utf-8")) <= 770_000
