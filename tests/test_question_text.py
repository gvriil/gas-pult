"""Владелец 24.11 (окно framewatcher): «варианты ответа видно, а вот вопроса не видно». Вопрос агента
(AskUserQuestion) — целиком над кнопками: длинный вопрос переносится на несколько строк, в конце бывает пояснение в
скобках без «?»; заголовок вкладки («☐ Раунд») — отдельно. В Telegram — первой строкой сообщения."""
from pathlib import Path

from gas_pult import humanize
from gas_pult.botparts.monitor import ask_title

SCR = (Path(__file__).resolve().parent / "fixtures" / "cc_screens" / "question.txt").read_text(encoding="utf-8")
LONG = SCR.replace("Какой отчёт прислать утром?",
                   "Какую сумму раунда написать на слайде для инвесторов? (диапазон или\nбез суммы — решите сами)") \
          .replace(" ☐ Отчёт", " ☐ Раунд  ✔ Submit")

Q = "Какую сумму раунда написать на слайде для инвесторов? (диапазон или без суммы — решите сами)"


def test_short_question_and_header():
    a = humanize.parse(SCR)
    assert a["kind"] == "question" and a["title_ru"] == "Какой отчёт прислать утром?" and a["header"] == "Отчёт"


def test_long_question_without_question_mark_at_end():
    a = humanize.parse(LONG)
    assert a["title_ru"] == Q
    assert a["header"] == "Раунд"
    assert [o["label_ru"] for o in a["options"]][:3] == ["Короткий", "Подробный", "Без отчёта"]


def test_telegram_first_line():
    assert ask_title(LONG) == "❓ Раунд: " + Q
    assert ask_title("просто экран без вопроса") == "Claude ждёт выбора:"


def test_panel_shows_header():
    web = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
    assert "a.header ?" in (web / "js/toolcard.js").read_text(encoding="utf-8")
    assert "a.header ?" in (web / "index.html").read_text(encoding="utf-8")
