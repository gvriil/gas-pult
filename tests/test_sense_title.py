"""Название чата по смыслу (владелец 19.11: «никаких непонятных автонаименований»): статус вроде «Ожидание
формулировки задачи» — не название; берём прежнее название по смыслу или первое сообщение человека."""

import json

from gas_pult import projects


def jl(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def test_status_detected():
    for t in ("Ожидание формулировки задачи", "Ожидает задачу", "Приветствие и знакомство", "Waiting for task",
              "New conversation", "Новый чат"):
        assert projects.is_status(t), t
    for t in ("Смета для клиента", "Настройка бота", "Отчёт за квартал"):
        assert not projects.is_status(t), t


def test_status_title_replaced_by_meaning(tmp_path):
    f = jl(tmp_path / "a.jsonl", [user("привет"), {"type": "ai-title", "aiTitle": "Ожидание формулировки задачи"}])
    assert projects.title_of(f) == "Ожидание формулировки задачи"            # смысла ещё нет — честно как есть
    f = jl(tmp_path / "b.jsonl", [user("привет"), {"type": "ai-title", "aiTitle": "Ожидание формулировки задачи"},
                                  user("составь смету на ремонт кухни для клиента до пятницы")])
    assert projects.title_of(f) == "Составь смету на ремонт кухни…"
    f = jl(tmp_path / "c.jsonl", [user("составь смету"), {"type": "ai-title", "aiTitle": "Смета на ремонт кухни"},
                                  {"type": "ai-title", "aiTitle": "Ожидание следующей задачи"}])
    assert projects.title_of(f) == "Смета на ремонт кухни"                  # последний статус не перетирает смысл
    f = jl(tmp_path / "d.jsonl", [user("x"), {"type": "ai-title", "aiTitle": "Настройка бота"}])
    assert projects.title_of(f) == "Настройка бота"


def test_first_words():
    assert projects.first_words("привет") == "" and projects.first_words("ну что там") == "Ну что там"


def test_offer_part_and_hook():
    from pathlib import Path
    web = Path(__file__).resolve().parents[1] / "src/gas_pult/web"
    page = (web / "index.html").read_text(encoding="utf-8")
    assert 'part("nametip").then((m) => m.watch(s))' in page
    js = (web / "js/nametip.js").read_text(encoding="utf-8")
    assert "Назвать чат" in js and "WAIT = 20000" in js and '"/api/title"' in js
    assert "SEEN[s.sid] = named; return;" in js                         # уже названный чат — без плашки
