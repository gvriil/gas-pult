"""«Ход работы» в чате (штаб 26.11, аудит Atoms п. 2): под строкой статуса — сворачиваемый список шагов. Строка статуса
не убрана; запрос /api/steps — только пока список раскрыт; без режима разработчика — общими словами; владельцу — по
флагу, по фокус-ссылке и наблюдателю — нет. Проверка по исходникам; вживую — /?demo&simple=0&open=@1&steps."""
from pathlib import Path

from gas_pult import access

WEB = Path(__file__).resolve().parents[1] / "src" / "gas_pult" / "web"
JS = (WEB / "js" / "steplog.js").read_text(encoding="utf-8")
CORE = (WEB / "index.html").read_text(encoding="utf-8")


def test_core_keeps_status_line_and_adds_containers():
    assert 'id="act" data-tour="status"' in CORE and 'id="sAct"' in CORE          # строка статуса на месте
    assert 'id="actLog" hidden' in CORE and 'id="sLog" hidden' in CORE and 'part("steplog")' in CORE
    assert len(CORE.encode("utf-8")) <= 770_000


def test_who_sees_it():
    assert 'role !== "viewer"' in JS and 'store("stepLog") === "1"' in JS and "!focus" in JS
    assert "/api/steps" not in access.FOCUS_GET                                  # фокус-ссылке шаги не отдаются


def test_plain_words_and_lazy_polling():
    assert "if (dev()) return s.what" in JS and "sKey(" in JS                     # без разработчика — без команд
    assert 'box.dataset.open === "1"' in JS and "% 3 === 0" in JS                 # опрос только раскрытого
