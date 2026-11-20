"""Бот называет чат по смыслу, а не служебным именем окна.

Владелец 19.11: «номера убрать, оставлять смысловой контекст».
"""
import json

from gas_pult import bot, projects


def pult(tmp_path):
    p = bot.Pult.__new__(bot.Pult)
    p.cfg = type("C", (), {"data": tmp_path})()
    p.home_of = lambda w: None
    return p


def test_own_title_wins(tmp_path):
    (tmp_path / projects.FILE).write_text(json.dumps({"sessions": {"s1": {"title": "План продаж"}}}), encoding="utf-8")
    assert pult(tmp_path).label({"id": "@1", "name": "gas-pult-1835", "sid": "s1", "path": "/x"}) == "План продаж"


def test_no_title_is_new_chat_not_window_name(tmp_path, monkeypatch):
    monkeypatch.setattr(bot.transcripts, "current", lambda *a: None)
    assert pult(tmp_path).label({"id": "@2", "name": "gas-pult-1835", "sid": "", "path": "/x"}) == "Новый чат"


def test_status_title_is_hidden(tmp_path):
    status = "Ожидание ответа"
    (tmp_path / projects.FILE).write_text(json.dumps({"sessions": {"s3": {"title": status}}}), encoding="utf-8")
    if projects.is_status(status):
        assert pult(tmp_path).label({"id": "@3", "name": "shtap-1", "sid": "s3", "path": "/x"}) == "Новый чат"


def test_no_window_name_in_bot_texts():
    from pathlib import Path
    src = Path(bot.__file__).read_text(encoding="utf-8")
    shown = [ln for ln in src.splitlines() if ("{w['name']}" in ln or '{w["name"]}' in ln)]
    assert shown == [], shown
