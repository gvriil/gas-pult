"""Форма «Сообщить об ошибке» (сообщения 23–24.11): не теряет текст при растягивании поля (papasan), отправка
Ctrl+Enter, картинка из буфера и микрофон (владелец). Поведение в браузере проверено Playwright в PR."""
from pathlib import Path

JS = (Path(__file__).resolve().parents[1] / "src/gas_pult/web/js/bugreport.js").read_text(encoding="utf-8")


def test_background_click_keeps_typed_text():
    assert 'downBg = e.target === bg' in JS and 'e.target === bg && downBg && !text.value.trim()' in JS


def test_ctrl_enter_paste_and_mic():
    assert '(e.ctrlKey || e.metaKey)' in JS and '$f("#bugGo").click()' in JS
    assert 'bg.addEventListener("paste"' in JS and 'x.type.startsWith("image/")' in JS
    assert 'id="bugMic"' in JS and 'part("voicejob")' in JS and "micHelp(" in JS
