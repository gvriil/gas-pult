"""Поручения вслух во время записи встречи (владелец 20.11): «Клод, запиши …» — отдельный пункт-поручение протокола;
«… отправь» — черновик, отправка только после «Да»."""
from gas_pult import meetings

LONG = ("Обсуждаем смету. Клод, запиши: Иван готовит смету до пятницы. Дальше про сроки, "
        "клод запиши перенести запуск на декабрь и отправь Анне! Ещё вопрос по складу? "
        "Гаврила, отправь Петру договор поставки. Claude, запиши - позвонить в банк\nНу и всё.")


def meeting(text):
    return {"started": 1000.0, "pieces": [{"at": 1000.0 + 3725, "kind": "запись", "text": text}]}


def test_commands_from_long_recording():
    c = meetings.commands(meeting(LONG))
    assert c == [
        {"at": "01:02", "kind": "note", "text": "Иван готовит смету до пятницы"},
        {"at": "01:02", "kind": "send", "text": "перенести запуск на декабрь Анне"},
        {"at": "01:02", "kind": "send", "text": "Петру договор поставки"},
        {"at": "01:02", "kind": "note", "text": "позвонить в банк"},
    ]


def test_no_wake_word_no_commands():
    assert meetings.commands(meeting("Запиши себе, отправь потом. Клод сказал, что всё ок.")) == []


def test_saved_next_to_transcript_and_in_prompt(tmp_path):
    m = meeting(LONG)
    folder, on = meetings.save(m, None, tmp_path)
    md = (folder / "поручения.md").read_text(encoding="utf-8")
    assert "- [01:02] Записать: Иван готовит смету до пятницы" in md and "отправка — после «Да»" in md
    p = meetings.prompt(folder, on, meetings.commands(m))
    assert p.startswith("Поручения, сказанные вслух") and "Отправить: Петру договор поставки" in p
    assert "сам не отправляй" in p and "только после моего «Да»" in p


def test_no_commands_no_file(tmp_path):
    m = meeting("Просто разговор без поручений.")
    folder, on = meetings.save(m, None, tmp_path)
    assert not (folder / "поручения.md").exists()
    assert meetings.prompt(folder, on, []).startswith("Протокол встречи.")
